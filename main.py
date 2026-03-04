
from run import start
from scenarios import siren

def main():
    simulation = start.Simulation()
    simulation.start_scenario()
    siren.siren_scenario(simulation)  
    simulation.close()


if __name__ == "__main__":
    main()
