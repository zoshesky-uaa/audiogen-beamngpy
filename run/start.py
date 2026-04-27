from time import sleep, time
import json
import os
import random

from beamngpy import BeamNGpy, Scenario
from beamngpy.logging import BNGDisconnectedError

import const
from run.beamng_home import BeamNGHomeNotFound, resolve_beamng_home
from run import scheduler
from spawns import vehicles, west_coast_usa


BEAMNG_USER_FOLDER = "beamng_user"
STABLE_USER_SETTINGS = {
    "SkipGenerateLicencePlate": True,
}


class Simulation:
    def __init__(self):
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
        self.on = True
        self.beamng.settings.set_nondeterministic()
        self.scenario_run_id = int(time() * 1000)
        self.current_time = "noon"
        self.event_scheduler = None
        self.scenario = None
        self.vehicle_controller = None
        self._background_traffic = []
        self._spawned_vehicles = []
        self.trial_valid = True
        self.abort_reason = None
        self.shutting_down = False
        self.controlled_targets = {0: 0, 1: 0}
        self.controlled_spawned = {0: 0, 1: 0}

    def invalidate_trial(self, reason, stop_run=False):
        if self.trial_valid:
            self.trial_valid = False
            self.abort_reason = reason
            print(f"Trial invalidated: {reason}")
        elif self.abort_reason is None:
            self.abort_reason = reason
        if stop_run and self.event_scheduler is not None:
            self.event_scheduler.tick.stop()
            self.event_scheduler.vehicle_update_tick.stop()

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

    def scenario_setup(self, count, ai=True):
        self.environment = random.choices([west_coast_usa.builder()], weights=[1], k=1)[0]

        scenario_name = f"Scenario_{self.scenario_run_id}_{count}"
        level_name = self.environment.name
        self.clean_scenario_startup(scenario_name, level_name)
        self.scenario = Scenario(level_name, scenario_name)
        self._background_traffic = []
        self._spawned_vehicles = []
        self.trial_valid = True
        self.abort_reason = None
        self.shutting_down = False
        self.controlled_targets = {0: 0, 1: 0}
        self.controlled_spawned = {0: 0, 1: 0}

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
        n_traffic_rand = random.randint(const.MINIMUM_TRAFFIC_VEHICLES, const.MAXIMUM_TRAFFIC_VEHICLES)
        control_count = min(n_traffic_rand, const.MAXIMUM_CONTROLLABLE_VEHICLES)
        self.controlled_targets[0] = control_count

        print(f"Number of traffic vehicles: {n_traffic_rand}. Setting up traffic vehicles.")
        for _ in range(n_traffic_rand):
            vehicle_ref = None
            if control_count > 0:
                control_count -= 1
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=False, control=True)
                if vehicle_ref is not None:
                    self.controlled_spawned[0] += 1
                    self.event_scheduler.append_event(0, vehicle_ref)
                else:
                    vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=False, control=False)
                    if vehicle_ref is not None:
                        self._background_traffic.append(vehicle_ref.vehicle)
            else:
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=False, control=False)
                if vehicle_ref is not None:
                    self._background_traffic.append(vehicle_ref.vehicle)
            if vehicle_ref is not None:
                # Do not set traffic AI mode during setup; this can block BeamNGpy.
                # TrafficEvent applies behavior after the scenario scheduler is running.
                print(f"Traffic vehicle {vehicle_ref.vid} successfully spawned")

        n_police_rand = random.randint(const.MINIMUM_EMERGENCY_VEHICLES, const.MAXIMUM_EMERGENCY_VEHICLES)
        control_count = min(n_police_rand, const.MAXIMUM_CONTROLLABLE_VEHICLES)
        self.controlled_targets[1] = control_count

        print(f"Number of emergency vehicles: {n_police_rand}. Setting up emergency vehicles.")
        for _ in range(n_police_rand):
            vehicle_ref = None
            if control_count > 0:
                control_count -= 1
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=True, control=True)
                if vehicle_ref is not None:
                    self.controlled_spawned[1] += 1
                    self.event_scheduler.append_event(1, vehicle_ref)
                else:
                    vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=True, control=False)
                    if vehicle_ref is not None:
                        self._background_traffic.append(vehicle_ref.vehicle)
            else:
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=True, control=False)
                if vehicle_ref is not None:
                    self._background_traffic.append(vehicle_ref.vehicle)
            if vehicle_ref is not None:
                vehicle_ref.vehicle.ai.set_mode("traffic")
                print(f"Emergency vehicle {vehicle_ref.vid} successfully spawned")

        missing_controlled = []
        if self.controlled_spawned[0] < self.controlled_targets[0]:
            missing_controlled.append(f"traffic {self.controlled_spawned[0]}/{self.controlled_targets[0]}")
        if self.controlled_spawned[1] < self.controlled_targets[1]:
            missing_controlled.append(f"emergency {self.controlled_spawned[1]}/{self.controlled_targets[1]}")
        if missing_controlled:
            self.invalidate_trial("Controlled source shortfall: " + ", ".join(missing_controlled))

        if self._background_traffic and self.trial_valid:
            self.beamng.traffic.start(self._background_traffic)

    def scenario_cleanup(self):
        self.shutting_down = True
        scheduler_ref = self.event_scheduler
        if scheduler_ref is not None:
            scheduler_ref.stop_all()
            scheduler_ref.finalize_trial(self.trial_valid, self.abort_reason)
            self.event_scheduler = None

        if self._background_traffic:
            try:
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
        self.on = False
        self.beamng.close()
