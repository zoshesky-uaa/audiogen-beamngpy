
from run import start
from const import TRAINING
# Number of simulations to run
SCENARIO_COUNT = 10


def main():
    print("Starting simulation...")
    # Initialize the simulation environment
    simulation = start.Simulation()
    simulation.beamng.ui.display_message("Starting simulation...")
    try:
        for i in range(SCENARIO_COUNT):
            print(f"Setting up Scenario {i+1}...")
            simulation.scenario_setup((i+1), ai=TRAINING)    

            print(f"Running Scenario {i+1}...")
            simulation.event_schedular.simulate()

            print(f"Cleaning up Scenario {i+1}...")
            simulation.scenario_cleanup()
    except KeyboardInterrupt:
        print("\nInterrupted — shutting down...")
        simulation.scenario_cleanup()
        exit(0)
    finally:
        print("Simulation ended.")
        simulation.close()
        exit(0)


if __name__ == "__main__":
    main()
