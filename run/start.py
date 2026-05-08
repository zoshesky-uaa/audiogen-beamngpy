from time import sleep, time
import json
import os
import random
import subprocess
from beamngpy import BeamNGpy, Scenario
from beamngpy.logging import BNGDisconnectedError
from pathlib import Path
import const
from run.beamng_home import BeamNGHomeNotFound, resolve_beamng_home
from run import scheduler
from spawns import vehicles, west_coast_usa
import threading

BEAMNG_USER_FOLDER = "beamng_user"
STABLE_USER_SETTINGS = {
    "SkipGenerateLicencePlate": True,
}
def _simulation_stopped(simulation):
    return simulation is not None and not getattr(simulation, "on", True)

def simulation_loop(simulation=None, scenario_count=None, training=None):
    if simulation is not None:
        simulation = None
    try:
        simulation = Simulation(scenario_count)
        simulation.beamng.ui.display_message("Starting simulation...")
        while (simulation.scenario_count >= 0):
            if _simulation_stopped(simulation):
                print("Simulation stopped; skipping remaining scenarios.")
                break

            print(f"Setting up " + simulation.project_name)
            simulation.scenario_setup(ai=training)

            print(f"Running " + simulation.project_name)
            simulation.event_scheduler.simulate()

            print(f"Cleaning up " + simulation.project_name)
            simulation.scenario_cleanup()
            simulation.scenario_count -= 1
    except KeyboardInterrupt:
        print("\nInterrupted - shutting down...")
        if simulation is not None:
            simulation.invalidate_trial("Interrupted by user", stop_run=True, permanent=True)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        if simulation is not None:
            simulation.invalidate_trial(f"Unexpected error: {e}", stop_run=True, permanent=True)
        raise
    finally:
        print("Simulation ended.")
        if simulation is not None:
            try:
                simulation.close()
            except Exception as e:
                print(f"Error closing simulation: {e}")

class Simulation:
    def __init__(self, scenario_count):
        self.scenario_count = scenario_count    
        self.create_temp_folder()
        try:
            beamng_home = resolve_beamng_home(getattr(const, "BEAMNG_LOCATION", None))
        except BeamNGHomeNotFound as e:
            raise RuntimeError(str(e)) from e

        self.beamng = BeamNGpy(
            host="localhost",
            port=25252,
            home=beamng_home,
            user=self.temp_folder,
            gfx="dx11",
        )

        def open_beamng(counter):
            try:
                self.beamng.open(launch=True)
            except BNGDisconnectedError:
                print("Retrying connection...")
                sleep(3)
                counter += 1
                if counter >= 10:
                    self.beamng.close()
                    raise RuntimeError("Could not connect to BeamNG")
                open_beamng(counter)

        open_beamng(0)
        self.beamng.settings.set_nondeterministic()
        self.current_time = "noon"
        self.event_scheduler = None
        self.scenario = None
        self.vehicle_controller = None
        self._background_traffic = []
        self._spawned_vehicles = []
        self.trial_valid = True
        self.abort_reason = None
        self.shutting_down = False
        self.controlled_spawned = 0
        self.process = None
        self.init = True
        self.thread = threading.current_thread()

        # Iterative zarr path creation, keep ahold of path for zarr label operations
        project_root = Path(__file__).resolve().parent.parent
        self.base_path = (project_root / 'trials').resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        # Find the next available trial index
        self.trial_count = 1
        while (self.base_path / f"trial_{self.trial_count}.zarr").exists():
            self.trial_count += 1
        self.project_name = f"trial_{self.trial_count}"
        self.zarr_path = self.base_path / f"{self.project_name}.zarr"

    def invalidate_trial(self, reason, stop_run=False, permanent=False):
        if self.trial_valid:
            self.trial_valid = False
            self.abort_reason = reason
            print(f"Trial invalidated: {reason}")
        elif self.abort_reason is None:
            self.abort_reason = reason
        if stop_run and self.event_scheduler is not None:
            self.shutting_down = True
            if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.event_scheduler.tick.stop()
            self.event_scheduler.vehicle_update_tick.stop()
            if fsm := getattr(self.event_scheduler, "fsm", None):
                fsm.zarr_cleanup()
            if not permanent:
                try:
                    self.scenario_cleanup()
                    self.close()
                except Exception as e:
                    print(f"Error closing BeamNG during restart: {e}")
                sleep(10)
                simulation_loop(None, self.scenario_count, training=const.TRAINING)
        if permanent:
            self.beamng.close()
            exit()

    def random_weather_setup(self):
        weather_presets = ["clear", "cloudy", "rainy", "stormy", "foggy"]
        # self.current_weather = random.choice(weather_presets)
        # self.beamng.env.set_weather_preset(self.current_weather, time=5)

    def create_temp_folder(self):
        self.temp_folder = os.path.abspath(BEAMNG_USER_FOLDER)
        os.makedirs(self.temp_folder, exist_ok=True)
        self._ensure_stable_user_settings()

    def _ensure_stable_user_settings(self):
        settings_dir = os.path.join(self.temp_folder, "current", "settings")
        os.makedirs(settings_dir, exist_ok=True)
        settings_path = os.path.join(settings_dir, "settings.json")

        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as settings_file:
                    loaded_settings = json.load(settings_file)
                    if isinstance(loaded_settings, dict):
                        settings = loaded_settings
            except (OSError, json.JSONDecodeError) as e:
                print(f"Could not read BeamNG settings; rewriting stable defaults: {e}")

        settings.update(STABLE_USER_SETTINGS)
        with open(settings_path, "w", encoding="utf-8") as settings_file:
            json.dump(settings, settings_file, indent=2)
            settings_file.write("\n")

    def random_tod_setup(self):
        time_presets = ["morning", "noon", "evening", "night"]
        self.current_time = random.choice(time_presets)
        match self.current_time:
            case "evening":
                self.beamng.env.set_tod(0.25)
            case "night":
                self.beamng.env.set_tod(0.5)
            case "morning":
                self.beamng.env.set_tod(0.75)
            case "noon":
                self.beamng.env.set_tod(1.0)

    def convert_to_imperial(self):
        self.beamng.settings.change("uiUnits", "imperial")
        self.beamng.settings.change("uiUnitLength", "imperial")
        self.beamng.settings.apply_graphics()

    def clean_scenario_startup(self, scenario_name=None, level_name=None):
        levels_path = os.path.join(self.temp_folder, "levels")
        if os.path.exists(levels_path):
            try:
                os.rmdir(levels_path)
                os.mkdir(levels_path)
            except OSError as e:
                print(f"Could not reset temp levels folder: {e}")

        if scenario_name is None or level_name is None:
            return
        try:
            if getattr(self.beamng, "_scenario", None):
                self.beamng.scenario.stop()
        except Exception:
            pass

        try:
            scenarios = self.beamng.scenario.get_level_scenarios(level_name)
            for scenario in scenarios:
                if scenario.name == scenario_name:
                    scenario.delete(self.beamng)
                    print(f"Deleted existing scenario: {scenario_name}")
                    break
        except Exception as e:
            print(f"Failed to delete scenario {scenario_name}: {e}")

    def _release_scenario_refs(self):
        scenario = self.scenario
        if scenario is not None:
            for vehicle in list(getattr(scenario, "vehicles", {}).values()):
                try:
                    vehicle.close()
                except Exception as e:
                    print(f"Failed to close vehicle {getattr(vehicle, 'vid', '<unknown>')}: {e}")
            try:
                scenario.bng = None
            except Exception:
                pass
        if getattr(self.beamng, "_scenario", None) is scenario:
            self.beamng._scenario = None
        self.scenario = None

    def scenario_setup(self, ai=True):
        if not self.init:
            self.trial_count = 1
            while (self.base_path / f"trial_{self.trial_count}.zarr").exists():
                self.trial_count += 1
            self.project_name = f"trial_{self.trial_count}"
            self.zarr_path = self.base_path / f"{self.project_name}.zarr"
        elif self.init:
            self.init = False
        
        self.environment = random.choices([west_coast_usa.builder()], weights=[1], k=1)[0]
        level_name = self.environment.name
        self.clean_scenario_startup(self.project_name, level_name)
        self.scenario = Scenario(level_name, self.project_name)
        self._background_traffic = []
        self._spawned_vehicles = []
        self.trial_valid = True
        self.abort_reason = None
        self.shutting_down = False
        self.controlled_spawned = 0

        self.vehicle_controller = vehicles.builder(simulation=self)
        self.event_scheduler = scheduler.Scheduler(self)
        self.vehicle_controller.driver_presetup(ai=ai)

        self.scenario.make(self.beamng)
        self.beamng.scenario.load(self.scenario)
        self.beamng.scenario.start()

        self.random_weather_setup()
        # BeamNG.tech can block on env.set_tod(...) after scenario.start().
        # Keep disabled until TOD is applied via a safer pre-start/scenario path.
        # self.random_tod_setup()
        self.convert_to_imperial()
        self.event_scheduler.transition_to_scenario()
        print("Scenario started.")

        self.vehicle_controller.get_road_network()
        self.simulation_traffic_setup()
        self.vehicle_controller.arm_driver_ai(ai=ai)

    def simulation_traffic_setup(self):
        n_traffic_rand = random.randint(1, const.MAXIMUM_TRAFFIC_VEHICLES)

        print(f"Number of traffic vehicles: {n_traffic_rand}. Setting up traffic vehicles.")
        for _ in range(n_traffic_rand):
            vehicle_ref = self.vehicle_controller.vehicle_spawn(control=False)
            if vehicle_ref is not None:
                self._background_traffic.append(vehicle_ref.vehicle)
  
        print(f"Number of emergency vehicles: {const.se_count*const.se_count}. Setting up emergency vehicles.")
        for event in range(const.se_count):
            for _ in range(const.track_count):
                vehicle_ref = self.vehicle_controller.vehicle_spawn(sound_class=event, control=True)
                if vehicle_ref is not None:
                    self.controlled_spawned += 1
                    self.event_scheduler.append_event(event, vehicle_ref)
                else:
                    print("Failed to spawn controlled emergency vehicle")

        missing_controlled = []
        if self.controlled_spawned < const.track_count*const.se_count:
            missing_controlled.append(f"emergency {self.controlled_spawned}/{const.track_count*const.se_count}")
        if missing_controlled:
            self.invalidate_trial("Controlled source shortfall: " + ", ".join(missing_controlled))

        if self._background_traffic and self.trial_valid:
            self.beamng.traffic.start(self._background_traffic)

    def scenario_cleanup(self):
        self.shutting_down = True
        if schedular := getattr(self, "event_scheduler", None):
            schedular.stop_all()
            self.event_scheduler = None

        if self._background_traffic:
            try:
                # Don't believe this does anything since the vehicles aren't techincally "traffic" AI
                self.beamng.traffic.stop()
            except Exception as e:
                print(f"Failed to stop background traffic: {e}")
            self._background_traffic.clear()

        for vehicle in reversed(self._spawned_vehicles):
            try:
                self.beamng.vehicles.despawn(vehicle)
            except Exception as e:
                print(f"Failed to despawn {getattr(vehicle, 'vid', '<unknown>')}: {e}")
            try:
                vehicle.close()
            except Exception:
                pass
        self._spawned_vehicles.clear()

        if self.scenario is not None:
            try:
                self.beamng.scenario.stop()
                sleep(1.0)
                self.scenario.delete(self.beamng)
            except Exception as e:
                print(f"Failed to stop/delete scenario: {e}")
            finally:
                self._release_scenario_refs()

    def close(self):
        self.scenario_cleanup()
        self.beamng.close()
