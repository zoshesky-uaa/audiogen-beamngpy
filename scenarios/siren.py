from main import Tick
from run import filesystem, se
import random
import threading
from time import sleep

def siren_scenario(simulation, driver):
    fsm = filesystem.FSM()
    ticker = Tick()
    ev_vehicle = simulation.random_emergency_vehicle()
    simulation.vehicle_setup(ev_vehicle, (-717, 101, 118), (0, 0, 0.3826834, 0.9238795))
    simulation.vehicle_connect(ev_vehicle)
    driver.switch()
    se1 = se.VehicleSoundEvent(class_index=3,
                               track_index=0,
                               beanmgpy=simulation.beamng,
                               vehicle=ev_vehicle,
                               driver=driver,
                               FSM=fsm,
                               tick=ticker)
    sleep(5)
    while ticker.frame_index < 1500:
        if not se1.active_event:
            print(f"Frame {ticker.frame_index}: No active event. Choosing next event...")
            chosen = random.choices([se1.random_empty, se1.random_siren_event],
                                    weights=[0.75, 0.25], k=1)[0]
            threading.Thread(target=chosen, daemon=True).start()

        ticker.iterate()
        sleep(0.1)