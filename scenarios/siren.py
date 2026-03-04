from run.scheduler import Scheduler
from time import sleep
import random

"""
Class Events:
1 = Other Vehicles
2 = Horn (broken currently)
3 = EV (Siren)
"""

def siren_scenario(simulation):
    sim_recorder = Scheduler(simulation)

    for i in range(random.randint(1, 10)):
        sim_recorder.append_event(3)

    for i in range(random.randint(5, 10)):
        sim_recorder.append_event(1)
    
    sleep(5)
    simulation.vehicle_controller.connect_to_driver(ai=True)
    sleep(random.randint(4, 8))
    sim_recorder.simulate()
    
