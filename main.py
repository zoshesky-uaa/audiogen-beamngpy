from const import TRAINING
from run import start

SCENARIO_COUNT = 100

def main():
    start.simulation_loop(scenario_count=SCENARIO_COUNT, training=TRAINING)

if __name__ == "__main__":
    main()
