from const import TRAINING
from run import start

SCENARIO_COUNT = 100

def main():
    print("Starting simulation...")
    start.simulation_loop(simulation=None, scenario_count=SCENARIO_COUNT, training=TRAINING)
    


if __name__ == "__main__":
    main()
