from const import TRAINING
from run import start


SCENARIO_COUNT = 10


def _simulation_stopped(simulation):
    return simulation is not None and not getattr(simulation, "on", True)


def main():
    print("Starting simulation...")
    simulation = None
    try:
        simulation = start.Simulation()
        simulation.beamng.ui.display_message("Starting simulation...")
        for i in range(SCENARIO_COUNT):
            if _simulation_stopped(simulation):
                print("Simulation stopped; skipping remaining scenarios.")
                break

            print(f"Setting up Scenario {i + 1}...")
            simulation.scenario_setup((i + 1), ai=TRAINING)

            print(f"Running Scenario {i + 1}...")
            simulation.event_scheduler.simulate()

            print(f"Cleaning up Scenario {i + 1}...")
            simulation.scenario_cleanup()
    except KeyboardInterrupt:
        print("\nInterrupted - shutting down...")
        if simulation is not None:
            simulation.invalidate_trial("Interrupted by user", stop_run=True)
            try:
                simulation.scenario_cleanup()
            except Exception as e:
                print(f"Error during cleanup: {e}")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        if simulation is not None:
            simulation.invalidate_trial(f"Unexpected error: {e}", stop_run=True)
            try:
                simulation.scenario_cleanup()
            except Exception as cleanup_e:
                print(f"Error during cleanup: {cleanup_e}")
        raise
    finally:
        print("Simulation ended.")
        if simulation is not None:
            try:
                simulation.close()
            except Exception as e:
                print(f"Error closing simulation: {e}")


if __name__ == "__main__":
    main()
