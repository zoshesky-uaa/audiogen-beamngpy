
from run import start

def main():
    print("Starting simulation...")
    simulation = start.Simulation()
    simulation.beamng.ui.display_message("Starting simulation...")
    try:
        i = 0
        while i < 2:
            simulation.scenario_setup((i+1), ai=True)         
            simulation.event_schedular.simulate()
            simulation.scenario_cleanup()
            i += 1
    except KeyboardInterrupt:
        print("\nInterrupted — shutting down...")
        simulation.scenario_cleanup()
        simulation.close()
    finally:
        print("Simulation ended.")
        simulation.close()


if __name__ == "__main__":
    main()
