
from run import start

SCENARIO_COUNT = 1

def main():
    print("Starting simulation...")
    simulation = start.Simulation()
    simulation.beamng.ui.display_message("Starting simulation...")
    try:
        i = 0
        while i < SCENARIO_COUNT:
            simulation.scenario_setup((i+1), ai=True)         
            simulation.event_schedular.simulate()
            simulation.scenario_cleanup()
            i += 1
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
