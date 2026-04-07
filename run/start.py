from beamngpy import BeamNGpy, Scenario
from beamngpy.logging import BNGDisconnectedError
from run import scheduler, dispatcher
import threading
from spawns import vehicles
from time import sleep
import random
import const
from spawns import west_coast_usa

class Simulation:
    def __init__(self):
        # BeamNGpy connection setup, debug mode enabled writes a tech log to %LOCALAPPDATA%\BeamNG.tech\<version>\
        self.beamng = BeamNGpy(
            host="localhost",        
            port=25252,           
            home=const.BEAMNG_LOCATION,
            debug=True,
            gfx='dx11'
        )

        # Helper recursion check for BeamNG connection
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
        #self.beamng.settings.set_deterministic(400)
        # Serializes calls for BeamNG, with a check for the simulation being on
        self.dispatcher = dispatcher.Dispatcher(lambda: self.on)
        self.dispatcher_thread = threading.Thread(target=self.dispatcher.run, daemon=True)
        self.dispatcher_thread.start()

    # Selects a random weather preset, not sure about all the options
    def random_weather_setup(self):
        # Get correct presets, some of these dont exist
        weather_presets = ['clear', 'cloudy', 'rainy', 'stormy', 'foggy']  
        #self.current_weather = random.choice(weather_presets)  
        #self.beamng.env.set_weather_preset(self.current_weather, time=5)

    # Selects a random time of day for simulation
    def random_tod_setup(self):
        time_presets =  ['morning', 'noon', 'evening', 'night'] 
        self.current_time = random.choice(time_presets)
        match self.current_time:
            case 'evening': self.beamng.env.set_tod(0.25)
            case 'night': self.beamng.env.set_tod(0.5)
            case 'morning': self.beamng.env.set_tod(0.75)
            case 'noon': self.beamng.env.set_tod(1.0)

    # Converts the simulation to imperial units
    def convert_to_imperial(self):
        self.beamng.settings.change('uiUnits', 'imperial')
        self.beamng.settings.change('uiUnitLength', 'imperial')
        self.beamng.settings.apply_graphics()

    # Does cleanup for existing scenarios that exists (unlikely) and does cleanup for their files (likely)
    def clean_scenario_startup(self, scenario_name, level_name):
        try:  
            if self.beamng._scenario:  
                self.beamng.scenario.stop()  
        except:  
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



    def scenario_setup(self, count, ai=True):
        # Environment choice
        self.environment = random.choices([west_coast_usa.builder()],
                                           weights=[1], k=1)[0]

        # Scenario setup
        scenario_name = f'Scenario_{count}'  
        level_name = self.environment.name
        self.scenario = Scenario(level_name, scenario_name) 
        self.clean_scenario_startup(scenario_name, level_name)

        # Intializes the vehicle controller, which handles location spawns based on the environment
        self.vehicle_controller = vehicles.builder(simulation=self)
    
        # Initializes the scheduler 
        self.event_scheduler = scheduler.Scheduler(self) 
        # Intializes the scenario and adds driver vehicle to it
        self.vehicle_controller.driver_presetup(ai=ai) 

        #Send sync for blocking each step to ensure they're loaded in order
        self.scenario.make(self.beamng)
        self.beamng.scenario.load(self.scenario)
        self.event_scheduler.transition_to_scenario()
        self.beamng.scenario.start()
        self.beamng.control.pause()
        # Setups conditions for the scenario
        self.random_weather_setup()
        self.random_tod_setup()
        self.convert_to_imperial()
        print("Scenario started.")
        
        # Gets the road network for the scenario for use in vehicle spawning
        self.vehicle_controller.get_road_network()

        # Spawns traffic and emergency vehicles
        self.simulation_traffic_setup() 

    def simulation_traffic_setup(self):
        # Traffic API is problematic spawning method, so I have to do this manually now
        n_traffic_rand = random.randint(const.MINIMUM_TRAFFIC_VEHICLES, const.MAXIMUM_TRAFFIC_VEHICLES)
        # Sets what vehicles can be controlled and given sound events within the maximum range
        control_count =  (n_traffic_rand % const.MAXIMUM_CONTROLLABLE_VEHICLES) + 1
        # Used to add delays between spawns to help out the Lua GE
        print("Number of traffic vehicles: " + str(n_traffic_rand) + ". Setting up traffic vehicles.")
            
        for i in range(n_traffic_rand):
            if control_count > 0:
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=False, control=True)
                self.event_scheduler.append_event(0, vehicle_ref)  
                control_count -= 1  
            else: 
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=False, control=False) 
                vehicle_ref.vehicle.ai.set_mode("traffic")
            print(f"Traffic vehicle {vehicle_ref.vid} successfully spawned")   

        # Spawns a random number of emergency vehicles based on the constants defined
        n_police_rand = random.randint(const.MINIMUM_EMERGENCY_VEHICLES, const.MAXIMUM_EMERGENCY_VEHICLES)
        control_count =  (n_police_rand % const.MAXIMUM_CONTROLLABLE_VEHICLES) + 1

        print("Number of emergency vehicles: " + str(n_police_rand) + ". Setting up emergency vehicles.")
        for i in range(n_police_rand):
            # Custom spawn for specifically emergency vehicles
            if control_count > 0:
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=True, control=True)
                self.event_scheduler.append_event(1, vehicle_ref)  
                control_count -= 1  
            else:  
                vehicle_ref = self.vehicle_controller.vehicle_spawn(EV=True, control=False)
                vehicle_ref.vehicle.ai.set_mode("traffic")
            print(f"Emergency vehicle {vehicle_ref.vid} successfully spawned")  

    # Stops all events, deletes the scenario, and despawns all vehicles if possible
    def scenario_cleanup(self):
        self.dispatcher.clear()    
        if hasattr(self, 'event_scheduler') and self.event_scheduler is not None:
            self.event_scheduler.stop_all()
            self.event_scheduler = None
        if hasattr(self, '_spawned_vehicles'):
            self._spawned_vehicles.clear()
        if hasattr(self, 'scenario') and self.scenario is not None:
            self.beamng.scenario.stop
            sleep(1.0)
            self.scenario.delete, self.beamng
            self.scenario = None  

    # Closes the connection to BeamNG and stops the dispatcher thread that recieves the commands
    def close(self):
        self.dispatcher.clear()
        self.beamng.close
        self.on = False
        self.dispatcher_thread.join(timeout=10.0)
        