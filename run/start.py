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
from run import exceptions, scheduler
from spawns import vehicles, west_coast_usa
import threading
import socket as _socket  
  
def _wait_for_port_free(host, port, timeout=15):  
    from time import time, sleep  
    deadline = time() + timeout  
    while time() < deadline:  
        try:  
            with _socket.create_connection((host, port), timeout=1):  
                sleep(0.5)  # still listening, wait  
        except (ConnectionRefusedError, OSError):  
            return  # port is free  
    raise RuntimeError(f"Port {port} still in use after {timeout}s")


BEAMNG_USER_FOLDER = "beamng_user"
STABLE_USER_SETTINGS = {
    "SkipGenerateLicencePlate": True,
}

def simulation_loop(scenario_count=None, training=None):
    print("Starting simulation...")
    simulation = Simulation()   
    while scenario_count >= 0:
        # State trackers for this specific trial iteration
        fatal_error = False
        print(f"Simulation count: {scenario_count}")
        try: 
            simulation.scenario_setup(ai=training)
            simulation.event_scheduler.simulate()

        except KeyboardInterrupt:
            print("\nInterrupted - shutting down...")
            if simulation is not None:
                simulation.invalidate_trial("Interrupted by user", stop_run=True)
            fatal_error = True
            
        except exceptions.RestartInterrupt as e:
            print(f"\n[Aborted Setup] {e}")
            
        except Exception as e:
            print(f"\nUnexpected error in main thread: {e}")
            if simulation is not None:
                simulation.invalidate_trial(f"Main thread error: {e}", stop_run=True)

        finally:            
            # 2. Teardown happens if the trial was marked invalid
            if simulation.trial_invalid.is_set() and not simulation.completed.is_set():
                # Only do the heavy restart teardown if we aren't trying to exit the script entirely
                if not fatal_error:
                    print(f"Trial failed ({simulation.abort_reason}). Tearing down BeamNG for restart...")

            print(f"Cleaning up scenario: {simulation.project_name}")
            try:
                simulation.scenario_cleanup()
            except Exception as e:
                print(f"Error attempting cleanup: {e}")

        # --- LOOP CONTROL RESOLUTION ---
        # Handled outside the try/except/finally structure to avoid Python overrides
        
        if fatal_error:
            break  # Actually exits the while loop now
            
        if not simulation.trial_invalid.is_set():
            scenario_count -= 1
        else:
            print(f"Retrying scenario {scenario_count}...")
            try:
                simulation.close()
            except Exception as e:
                print(f"Error during teardown close (Safe to ignore): {e}")
            _wait_for_port_free("localhost", 25252) 
            simulation.launch_beamng()  # Relaunch BeamNG for a fresh start on the next iteration

    # Out of the loop
    print("Simulation sequence ended.")
    if simulation is not None:
        try:
            simulation.close()
        except Exception as e:
            print(f"Error closing simulation: {e}")

class Simulation:
    def __init__(self):
        self.create_temp_folder()
        try:
            self.beamng_home = resolve_beamng_home(getattr(const, "BEAMNG_LOCATION", None))
        except BeamNGHomeNotFound as e:
            raise RuntimeError(str(e)) from e
        
        self.launch_beamng()
        self.beamng.settings.set_nondeterministic()
        self.current_time = "noon"
        self.event_scheduler = None
        self.scenario = None
        self.vehicle_controller = None
        self._background_traffic = []
        self._spawned_vehicles = []
        self.abort_reason = None
        self.controlled_spawned = 0
        self.process = None
        self.init = True
        self.trial_invalid = threading.Event()
        self.completed = threading.Event()

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

    def launch_beamng(self):
        self.beamng = BeamNGpy(
            host="localhost",
            port=25252,
            home=self.beamng_home,
            user=self.temp_folder,
            gfx="dx11",
        )

        for attempt in range(10):
            try:
                self.beamng.open(launch=True)
                break
            except BNGDisconnectedError:
                print(f"Retrying connection... (Attempt {attempt + 1}/10)")
                sleep(3)
        else:
            self.beamng.close()
            raise RuntimeError("Could not connect to BeamNG")

    def invalidate_trial(self, reason, stop_run=False):
        if not self.completed.is_set():
            if not self.trial_invalid.is_set():
                self.trial_invalid.set()
                self.abort_reason = reason
                print(f"Trial invalidated: {reason}")

            elif self.abort_reason is None:
                self.abort_reason = reason

            if stop_run and self.event_scheduler is not None:
                # Halt the schedulers so threads gracefully exit
                self.event_scheduler.tick.stop()
                self.event_scheduler.vehicle_update_tick.stop()
                
                # Signal the FSM but do not invoke BeamNG cleanups here
                if fsm := getattr(self.event_scheduler, "fsm", None):
                    fsm.zarr_cleanup()


    @exceptions.interruptable
    def random_weather_setup(self):
        weather_presets = ["clear", "cloudy", "rainy", "stormy", "foggy"]
        # self.current_weather = random.choice(weather_presets)
        # self.beamng.env.set_weather_preset(self.current_weather, time=5)

    @exceptions.interruptable
    def create_temp_folder(self):
        self.temp_folder = os.path.abspath(BEAMNG_USER_FOLDER)
        os.makedirs(self.temp_folder, exist_ok=True)
        self._ensure_stable_user_settings()

    @exceptions.interruptable
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

    @exceptions.interruptable
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

    @exceptions.interruptable
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

    @exceptions.interruptable
    def scenario_setup(self, ai=True):
        print(f"Setting up scenario: {self.project_name}")
        self.environment = random.choices([west_coast_usa.builder()], weights=[1], k=1)[0]
        level_name = self.environment.name
        self.clean_scenario_startup(self.project_name, level_name)
        self.scenario = Scenario(level_name, self.project_name)

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
        self.event_scheduler.append_event(99, self.vehicle_controller.driver_ref, ai)

    @exceptions.interruptable
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

        if self._background_traffic and self.trial_invalid:
            self.beamng.traffic.start(self._background_traffic)

    def scenario_cleanup(self):
        if schedular := getattr(self, "event_scheduler", None):
            schedular.stop_all()

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
                sleep(5.0)
                self.scenario.delete(self.beamng)
            except Exception as e:
                print(f"Failed to stop/delete scenario: {e}")
            finally:
                self._release_scenario_refs()
        
        if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        
        self.trial_count = 1
        while (self.base_path / f"trial_{self.trial_count}.zarr").exists():
            self.trial_count += 1
        self.project_name = f"trial_{self.trial_count}"
        self.zarr_path = self.base_path / f"{self.project_name}.zarr"

        self._background_traffic = []
        self._spawned_vehicles = []
        self.abort_reason = None
        self.controlled_spawned = 0
        self.trial_invalid.clear()
        self.completed.clear()
        self.event_scheduler = None
        self.scenario = None
        self.vehicle_controller = None
        self.process = None

    def close(self):
        self.scenario_cleanup()
        self.beamng.close()
