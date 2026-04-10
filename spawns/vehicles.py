from beamngpy import Vehicle
import random
import math
from beamngpy import angle_to_quat 
from beamngpy.sensors import Damage, RoadsSensor, Electrics
from collections import namedtuple
import threading

class builder:
    def __init__(self, simulation):
        self.name = None
        self.simulation = simulation
        self.driver_ref = None
        self.roads = None
        self.traffic_count = 0
        self.ev_count = 0
    
    def get_road_network(self):
        road_network = self.simulation.beamng.scenario.get_road_network()

        self.roads = [
            road for road in road_network.values() 
            if 'edges' in road and len(road['edges']) > 1
        ]
        

    def road_random_spawn(self):
        #Pick a random valid road
        chosen_road = random.choice(self.roads)
        points = chosen_road['edges']
    
        # Pick a random segment along that road (up to the second-to-last node)
        idx = random.randint(0, len(points) - 2)

        # Randomly pick the left or right side of the road
        side = random.choice(['left', 'right'])   

        # Extract coordinates for the chosen side
        p1 = points[idx][side]
        p2 = points[idx + 1][side]
        
        # Calculate heading between point 1 and point 2
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        heading = math.atan2(dy, dx)

        # Flip sides if on the left
        if side == 'left':
            heading += math.pi   

        # Generate the spawn dictionary format
        pos = (p1[0], p1[1], p1[2])
        rot_quat = angle_to_quat((0, 0, heading))
        
        return pos, rot_quat

    # Main thread operation
    def vehicle_spawn(self, EV=False, control=False):
        spawn = self.road_random_spawn()
        if EV:
            template = self.random_EV()
            vehicle = Vehicle(
                vid=template.vid + f" EV_{self.ev_count}",
                model=template.options.get('model'),
                part_config=template.options.get('partConfig'),
                licence=template.options.get('licence')
            )
            self.ev_count += 1
        else:
            template = self.random_vehicle()
            vehicle = Vehicle(
                vid=template.vid + f" TV_{self.traffic_count}",
                model=template.options.get('model'),
                part_config=template.options.get('partConfig'),
                licence=template.options.get('licence')
            )
            self.traffic_count += 1
        self.simulation.beamng.vehicles.spawn(vehicle, pos=spawn[0], rot_quat=spawn[1], cling=True, connect=True)
        veh_ref = Vehicle_Reference(vehicle, self.simulation.event_scheduler.vehicle_update_tick, self.simulation.beamng, control)
        return veh_ref
    
    # Main thread operation
    def driver_presetup(self, ai=True):
        # Driver must have a position before the scenario is loaded and loaded before scenario is made,
        # So therefore I had to extract random positions, getting a better list is ideal
        spawn = self.simulation.environment.random_location()
        driver = self.random_vehicle()
        # Store the driver reference
        self.simulation.scenario.add_vehicle(driver, pos=spawn[0], rot_quat=spawn[1], cling=True)
        self.driver_ref = Vehicle_Reference(driver, self.simulation.event_scheduler.vehicle_update_tick, self.simulation.beamng, control=True, driver=True)
        self.simulation.event_scheduler.append_event(99, ai=ai)

    def random_EV(self):
        return random.choice(EV)

    def random_vehicle(self):
        return random.choice(NORMAL)
    
    def random_traffic(self):
        return random.choice(OTHER)

VehicleState = namedtuple('VehicleState', ['position', 'velocity', 'steering', 'braking', 'damage', 'lane_data'])
class Vehicle_Reference:
    def __init__(self, vehicle, tick, beamng, control=False, driver=False):
        # Vehicle objects are thread-safe as of 1.30
        self.vehicle = vehicle
        self.tick = tick
        self.beamng = beamng
        self.vid = vehicle.vid
        if control:
            if driver:
                print(f"Driver vehicle {self.vid} intialized")  
                self.state = VehicleState((0.0,0.0,0.0), (0.0,0.0,0.0), 0.0, 0.0, 0.0, (0.0,0.0,0.0,0.0))
                thread = threading.Thread(target=self.driver_run, daemon=True)
                thread.start()
            else:
                print(f"Sound event vehicle {self.vid} intialized")  
                self.state = VehicleState((0.0,0.0,0.0), (0.0,0.0,0.0), 0.0, 0.0, 0.0, (0.0,0.0,0.0,0.0))
                thread = threading.Thread(target=self.run, daemon=True)
                thread.start()

    def run(self):
        self.tick.waited_action()
        self.tick.waited_action_iterate(self.update)

    def driver_run(self):
        self.tick.waited_action()
        self.electrics = Electrics()
        self.vehicle.sensors.attach("electrics", self.electrics)
        self.damage = Damage()
        self.vehicle.sensors.attach("damage", self.damage)
        self.roads_sensor = RoadsSensor(name="roads_sensor", bng=self.beamng, vehicle=self.vehicle)        
        self.tick.waited_action_iterate(self.update)

    def update(self):
        if hasattr(self, 'electrics') and hasattr(self, 'damage') and hasattr(self, 'roads_sensor'):
            self.vehicle.sensors.poll('state','electrics', 'damage')
            position = self.vehicle.state['pos']
            velocity = self.vehicle.state['vel']
            steering = self.electrics['steering']
            braking = self.electrics['brake']
            damage = self.damage['damage']
            road_data = self.roads_sensor.poll()
            if isinstance(road_data, dict) and road_data:
                latest_time = max(road_data.keys())  
                latest_reading = road_data[latest_time]  
                lane_center = latest_reading["dist2CL"] * 3.281  
                lane_right = latest_reading["dist2Right"] * 3.281    
                lane_left = latest_reading["dist2Left"] * 3.281  
                lane_halfwidth = latest_reading["halfWidth"] * 3.281  
                lane_data = (lane_center, lane_right, lane_left, lane_halfwidth)  
            else:
                lane_data = (0.0, 0.0, 0.0, 0.0)
            self.state = VehicleState(position, velocity, steering, braking, damage, lane_data)
        else:
            self.vehicle.sensors.poll('state')
            position = self.vehicle.state['pos']
            velocity = self.vehicle.state['vel']
            self.state = VehicleState(position, velocity, 0.0, 0.0, 0.0, (0.0, 0.0, 0.0, 0.0))

EV = [
    Vehicle('(Vehicle) Wydra Rescue (CVT)', model='atv', part_config='vehicles/atv/rescue.pc', licence='EV'),
    Vehicle('(Vehicle) Bolide 350 Polizia (M)', model='bolide', part_config='vehicles/bolide/polizia.pc', licence='EV'),
    Vehicle('(Vehicle) FCV Vivace Polizia (M)', model='vivace', part_config='vehicles/vivace/vivace_polizia.pc', licence='EV'),
    Vehicle('(Vehicle) FCV Vivace S Gendarmerie (DCT)', model='vivace', part_config='vehicles/vivace/vivace_S_gendarmerie.pc', licence='EV'),
    Vehicle('(Vehicle) FCV Tograc Polizia (M)', model='vivace', part_config='vehicles/vivace/tograc_polizia.pc', licence='EV'),
    Vehicle('(Vehicle) Hopper Carabinieri (M)', model='hopper', part_config='vehicles/hopper/carabinieri.pc', licence='EV'),
    Vehicle('(Vehicle) Hopper Sheriff (M)', model='hopper', part_config='vehicles/hopper/sheriff.pc', licence='EV'),
    Vehicle('(Vehicle) Scintilla GTs Polizia (DCT)', model='scintilla', part_config='vehicles/scintilla/gts_polizia.pc', licence='EV'),
    Vehicle('(Vehicle) Pessima Police (A)', model='midsize', part_config='vehicles/midsize/police.pc', licence='EV'),
    Vehicle('(Vehicle) Covet Police (A)', model='covet', part_config='vehicles/covet/police.pc', licence='EV'),
    Vehicle('(Vehicle) Wendover Police Interceptor (A)', model='wendover', part_config='vehicles/wendover/interceptor.pc', licence='EV'),
    Vehicle('(Vehicle) Bluebuck Police Package (A)', model='bluebuck', part_config='vehicles/bluebuck/police.pc', licence='EV'),
    Vehicle('(Vehicle) Bluebuck Police Interceptor (A)', model='bluebuck', part_config='vehicles/bluebuck/interceptor.pc', licence='EV'),
    Vehicle('(Vehicle) D-Series D45 Off-Road Ambulance (A)', model='pickup', part_config='vehicles/pickup/d45_diesel_4wd_ambulance_A.pc', licence='EV'),
    Vehicle('(Vehicle) Special 313 V8 4-Door Sedan Police Package (A)', model='burnside', part_config='vehicles/burnside/4door_late_v8_3A_police.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer Fire Chief (A)', model='roamer', part_config='vehicles/roamer/firechief.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer Belasco City Police Department (A)', model='roamer', part_config='vehicles/roamer/police.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer LXT35 Police Package (Unmarked) (A)', model='roamer', part_config='vehicles/roamer/unmarked.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer Sheriff (A)', model='roamer', part_config='vehicles/roamer/sheriff.pc', licence='EV'),
    Vehicle('(Vehicle) MD-Series MD60 Armored Police (M)', model='md_series', part_config='vehicles/md_series/md_60_armored_police.pc', licence='EV'),
    Vehicle('(Vehicle) MD-Series MD70 Ambulance 4WD (M)', model='md_series', part_config='vehicles/md_series/md_70_ambulance_4wd.pc', licence='EV'),
    Vehicle('(Vehicle) MD-Series MD60 Ambulance (A)', model='md_series', part_config='vehicles/md_series/md_60_ambulance.pc', licence='EV'),
    Vehicle('(Vehicle) Bastion Police (Unmarked) 5.7 AWD (A)', model='bastion', part_config='vehicles/bastion/police_unmarked_v8_awd_A.pc', licence='EV'),
    Vehicle('(Vehicle) Bastion Police 5.7 AWD (A)', model='bastion', part_config='vehicles/bastion/police_v8_awd_A.pc', licence='EV'),
    Vehicle('(Vehicle) LeGran Fire Chief (Facelift) (A)', model='legran', part_config='vehicles/legran/firechief.pc', licence='EV'),
    Vehicle('(Vehicle) Grand Marshal Belasco City Police Department (A)', model='fullsize', part_config='vehicles/fullsize/bcpd.pc', licence='EV'),
    Vehicle('(Vehicle) Grand Marshal Police Package (Unmarked) (A)', model='fullsize', part_config='vehicles/fullsize/unmarked.pc', licence='EV'),
    Vehicle('(Vehicle) Grand Marshal Police Package (A)', model='fullsize', part_config='vehicles/fullsize/police.pc', licence='EV'),
    Vehicle('(Vehicle) D-Series D45 Ambulance (A)', model='pickup', part_config='vehicles/pickup/d45_ambulance_A.pc', licence='EV'),
    Vehicle('(Vehicle) Sunburst Polizia (DCT)', model='sunburst2', part_config='vehicles/sunburst2/polizia.pc', licence='EV'),
    Vehicle('(Vehicle) Sunburst Gendarmerie (DCT)', model='sunburst2', part_config='vehicles/sunburst2/gendarmerie.pc', licence='EV'),
    Vehicle('(Vehicle) Sunburst Police Package (CVT)', model='sunburst2', part_config='vehicles/sunburst2/police.pc', licence='EV'),
    Vehicle('(Vehicle) Sunburst Police Interceptor (DCT)', model='sunburst2', part_config='vehicles/sunburst2/interceptor.pc', licence='EV'),
    Vehicle('(Vehicle) Lansdale 3.3 S Police (A)', model='lansdale', part_config='vehicles/lansdale/33_police_late_A.pc', licence='EV'),
]


NORMAL = [
    Vehicle('(Vehicle) H-Series H35 Vanster Long Wheelbase (A)', model='van', part_config='vehicles/van/h35_ext_vanster.pc', licence='DRIVER'),
    Vehicle('(Vehicle) I-Series 2400i (A)', model='etki', part_config='vehicles/etki/2400i_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Grand Marshal V8 Luxe (A)', model='fullsize', part_config='vehicles/fullsize/luxe.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Tograc qE', model='vivace', part_config='vehicles/vivace/tograc_qE.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Lansdale 2.5 Sport S (M)', model='lansdale', part_config='vehicles/lansdale/25_S_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.5 Sport RS AWD Wagon (DCT)', model='sunburst2', part_config='vehicles/sunburst2/sport_RS_wagon_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima 1.8 DX TurboBurger (A)', model='midsize', part_config='vehicles/midsize/turboburger.pc', licence='DRIVER'),
    Vehicle('(Vehicle) D-Series D10 Charro V8 4WD (A)', model='pickup', part_config='vehicles/pickup/d10_4wd_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) 800-Series 844 250 (M)', model='etk800', part_config='vehicles/etk800/844_250_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima 1.8 HX (M)', model='pessima', part_config='vehicles/pessima/HX_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Vivace 230S (DCT)', model='vivace', part_config='vehicles/vivace/vivace_230S_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Wendover 3300 (A)', model='wendover', part_config='vehicles/wendover/base_v6_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) H-Series H35 Vanster Long Wheelbase (A)', model='van', part_config='vehicles/van/h35_ext_vanster.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Regulier Wagon (Facelift) (M)', model='legran', part_config='vehicles/legran/base_i4_wagon_facelift_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) BX-Series 240BX Coupe DX (A)', model='bx', part_config='vehicles/bx/240bx_coupe_dx_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.5 Sport RS-Aero AWD Wagon (DCT)', model='sunburst2', part_config='vehicles/sunburst2/sport_RS2_wagon_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Grand Marshal Taxi (A)', model='fullsize', part_config='vehicles/fullsize/taxi.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.5 Sport RS AWD Wagon (DCT)', model='sunburst2', part_config='vehicles/sunburst2/sport_RS_wagon_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.5 Sport RS AWD Wagon (DCT)', model='sunburst2', part_config='vehicles/sunburst2/sport_RS_wagon_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Sport S (M)', model='legran', part_config='vehicles/legran/sport_s_i4_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Luxe V6 (A)', model='legran', part_config='vehicles/legran/luxe_v6_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) K-Series Kc6x 360 (A)', model='etkc', part_config='vehicles/etkc/kc6x_360_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) D-Series D15 Fleet Extended Cab (M)', model='pickup', part_config='vehicles/pickup/d15_fleet_ext_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Grand Marshal Fleet (A)', model='fullsize', part_config='vehicles/fullsize/fleet.pc', licence='DRIVER'),
    Vehicle('(Vehicle) K-Series Kc4 250 (A)', model='etkc', part_config='vehicles/etkc/kc4_250_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima 2.7 LX V6 Sport (M)', model='midsize', part_config='vehicles/midsize/LX_V6_sport_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Vivace 110 (M)', model='vivace', part_config='vehicles/vivace/vivace_110_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) D-Series D25 V8 4WD Extended Cab Long Bed (M)', model='pickup', part_config='vehicles/pickup/d25_ext_longbed_4wd_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Lansdale 2.2 Cargo (A)', model='lansdale', part_config='vehicles/lansdale/22_cargo_late_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Lansdale Turbo Tuner (M)', model='lansdale', part_config='vehicles/lansdale/25_tuner_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Sport S (M)', model='legran', part_config='vehicles/legran/sport_s_i4_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Tograc 160Q (M)', model='vivace', part_config='vehicles/vivace/tograc_160q_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) 800-Series 844 250 (M)', model='etk800', part_config='vehicles/etk800/844_250_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima 2.7 LX V6 Sport GTz (M)', model='midsize', part_config='vehicles/midsize/special.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Roamer V8 4WD LXT (M)', model='roamer', part_config='vehicles/roamer/v8_4wd_lxt_m.pc', licence='DRIVER'),
    Vehicle('(Vehicle) K-Series Kc6x 360 (A)', model='etkc', part_config='vehicles/etkc/kc6x_360_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) I-Series 2400 (M)', model='etki', part_config='vehicles/etki/2400_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) BX-Series 240BX Coupe LX (M)', model='bx', part_config='vehicles/bx/240bx_coupe_lx_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) MD-Series MD60 School Bus JATO (M)', model='md_series', part_config='vehicles/md_series/md_60_schoolbus_jato.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Lansdale 3.8 Sport SE AWD (A)', model='lansdale', part_config='vehicles/lansdale/38_SE_sport_AWD_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Bastion Sport 5.7 (M)', model='bastion', part_config='vehicles/bastion/sport_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) 800-Series 844 150 (M)', model='etk800', part_config='vehicles/etk800/844_150_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) D-Series D25 V8 Crew Cab Dually (A)', model='pickup', part_config='vehicles/pickup/d25_crew_dually_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) 800-Series 844 250 (M)', model='etk800', part_config='vehicles/etk800/844_250_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.5 Sport RS-Aero AWD Wagon (DCT)', model='sunburst2', part_config='vehicles/sunburst2/sport_RS2_wagon_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) BX-Series 240BX LXz (M)', model='bx', part_config='vehicles/bx/240bx_hatch_lxz_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Roamer V8 4WD (M)', model='roamer', part_config='vehicles/roamer/v8_4wd_m.pc', licence='DRIVER'),
    Vehicle('(Vehicle) BX-Series 240BX Coupe DX (A)', model='bx', part_config='vehicles/bx/240bx_coupe_dx_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.0 Base FWD (CVT)', model='sunburst2', part_config='vehicles/sunburst2/base_CVT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.0 Base FWD (CVT)', model='sunburst2', part_config='vehicles/sunburst2/base_CVT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) H-Series H25 4WD XT Passenger (A)', model='van', part_config='vehicles/van/h25_passenger_4wd_xt.pc', licence='DRIVER'),
    Vehicle('(Vehicle) 800-Series 844 150 (M)', model='etk800', part_config='vehicles/etk800/844_150_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima Street Tuned (M)', model='midsize', part_config='vehicles/midsize/custom.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Covet 1.5 LXi (A)', model='covet', part_config='vehicles/covet/LXi_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Roamer V8 4WD (M)', model='roamer', part_config='vehicles/roamer/v8_4wd_m.pc', licence='DRIVER'),
    Vehicle('(Vehicle) D-Series D45 Cargo Box Upfit (A)', model='pickup', part_config='vehicles/pickup/d45_cargobox_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Luxe V6 (A)', model='legran', part_config='vehicles/legran/luxe_v6_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima 1.8 DX (A)', model='midsize', part_config='vehicles/midsize/DX_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Wendover Sport SE 3800 (Facelift) (M)', model='wendover', part_config='vehicles/wendover/sport_se_v6_M_facelift.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Pessima 2.7 LX V6 Sport (M)', model='midsize', part_config='vehicles/midsize/LX_V6_sport_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Grand Marshal Limousine V8 (A)', model='fullsize', part_config='vehicles/fullsize/limo_base.pc', licence='DRIVER'),
    Vehicle('(Vehicle) H-Series H45 Cabster Cargo Box Upfit (A)', model='van', part_config='vehicles/van/deliverytruck.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Sunburst 2.5 Sport RS AWD Wagon (DCT)', model='sunburst2', part_config='vehicles/sunburst2/sport_RS_wagon_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Vivace E', model='vivace', part_config='vehicles/vivace/vivace_E.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Covet 1.5 DXi (M)', model='covet', part_config='vehicles/covet/DXi_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Wendover Sport S 3800 (Facelift) (A)', model='wendover', part_config='vehicles/wendover/sport_s_v6_A_facelift.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Vivace 160 (M)', model='vivace', part_config='vehicles/vivace/vivace_160_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) T-Series TC82 Base (M)', model='us_semi', part_config='vehicles/us_semi/tc82_base.pc', licence='DRIVER'),
    Vehicle('(Vehicle) H-Series H35 Vanster Long Wheelbase (A)', model='van', part_config='vehicles/van/h35_ext_vanster.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Sport S (M)', model='legran', part_config='vehicles/legran/sport_s_i4_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) LeGran Regulier Wagon (Facelift) (M)', model='legran', part_config='vehicles/legran/base_i4_wagon_facelift_M.pc', licence='DRIVER'),
    Vehicle('(Vehicle) FCV Vivace S 270 (DCT)', model='vivace', part_config='vehicles/vivace/vivace_S_270_DCT.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Lansdale 2.5 Taxi (A)', model='lansdale', part_config='vehicles/lansdale/25_taxi_A.pc', licence='DRIVER'),
    Vehicle('(Vehicle) Bastion Luxe 5.7 (A)', model='bastion', part_config='vehicles/bastion/luxe_v8_A.pc', licence='DRIVER'),
]

OTHER = [
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series Vanster', model='simple_traffic', part_config='vehicles/simple_traffic/van_vanster.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK I-Series 2400i', model='simple_traffic', part_config='vehicles/simple_traffic/etki_eu_facelift.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Grand Marshal V8 Luxe', model='simple_traffic', part_config='vehicles/simple_traffic/fullsize_luxe.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Tograc qE', model='simple_traffic', part_config='vehicles/simple_traffic/tograc_ev.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale S', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_pre_mid.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_sedan_wide.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (New) Turboburger', model='simple_traffic', part_config='vehicles/simple_traffic/midsize_turboburger.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_sedan_wide.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril D-Series Charro 4WD', model='simple_traffic', part_config='vehicles/simple_traffic/pickup_d10.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series xc Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_eu_xc.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (Old) HX', model='simple_traffic', part_config='vehicles/simple_traffic/pessima_aero.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Vivace 230S', model='simple_traffic', part_config='vehicles/simple_traffic/vivace_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Wendover 3300', model='simple_traffic', part_config='vehicles/simple_traffic/wendover_pre_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series Vanster Beamcom', model='simple_traffic', part_config='vehicles/simple_traffic/van_beamcom.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Sedan Regulier', model='simple_traffic', part_config='vehicles/simple_traffic/legran_sedan_pre_regulier.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu BX-Series DX Hatchback', model='simple_traffic', part_config='vehicles/simple_traffic/bx_base_hatch.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS-Aero Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_wagon_aero.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Grand Marshal Taxi', model='simple_traffic', part_config='vehicles/simple_traffic/fullsize_taxi.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_wagon_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_sedan_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Sedan S', model='simple_traffic', part_config='vehicles/simple_traffic/legran_sedan_pre_s.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Wagon Luxe', model='simple_traffic', part_config='vehicles/simple_traffic/legran_wagon_pre_luxe.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK K-Series kc6x 360', model='simple_traffic', part_config='vehicles/simple_traffic/etkc_kc6.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril D-Series Fleet Extended Cab', model='simple_traffic', part_config='vehicles/simple_traffic/pickup_d25.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Grand Marshal Fleet', model='simple_traffic', part_config='vehicles/simple_traffic/fullsize_fleet.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK K-Series kc4 250', model='simple_traffic', part_config='vehicles/simple_traffic/etkc_kc4.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (Old) LX', model='simple_traffic', part_config='vehicles/simple_traffic/pessima_standard.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Vivace 110', model='simple_traffic', part_config='vehicles/simple_traffic/vivace_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale S Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_facelift_mid.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril D-Series 4WD ', model='simple_traffic', part_config='vehicles/simple_traffic/pickup_d15.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale Cargo Van', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_pre_van.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_pre_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Sedan Sport', model='simple_traffic', part_config='vehicles/simple_traffic/legran_sedan_pre_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Tograc 160Q', model='simple_traffic', part_config='vehicles/simple_traffic/tograc_standard.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 250 Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_eu_high_wagon.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (Old) GTz', model='simple_traffic', part_config='vehicles/simple_traffic/pessima_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Roamer V8 4WD LXT', model='simple_traffic', part_config='vehicles/simple_traffic/roamer_ext.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK K-Series kc6x 360', model='simple_traffic', part_config='vehicles/simple_traffic/etkc_eu_kc6.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK I-Series 2400', model='simple_traffic', part_config='vehicles/simple_traffic/etki_pre.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu BX-Series LX Coupe', model='simple_traffic', part_config='vehicles/simple_traffic/bx_sport_coupe.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK I-Series 2400', model='simple_traffic', part_config='vehicles/simple_traffic/etki_eu_pre.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Covet Driving School Car', model='simple_traffic', part_config='vehicles/simple_traffic/covet_drivingschool.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale SE AWD', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_pre_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_facelift_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell Bastion Sport', model='simple_traffic', part_config='vehicles/simple_traffic/bastion_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Roamer V8 4WD LXT Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/roamer_ext_facelift.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 150 Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_base_wagon.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril D-Series Crew Cab Dually', model='simple_traffic', part_config='vehicles/simple_traffic/pickup_d35.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 250 Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_eu_high_sedan.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS-Aero Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_sedan_aero.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Sedan Regulier Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/legran_sedan_facelift_regulier.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu BX-Series LXz Hatchback', model='simple_traffic', part_config='vehicles/simple_traffic/bx_sport_hatch.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Roamer V8 Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/roamer_base_facelift.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu BX-Series DX Coupe', model='simple_traffic', part_config='vehicles/simple_traffic/bx_base_coupe.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Base Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_sedan_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Base Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_wagon_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK I-Series 2400i', model='simple_traffic', part_config='vehicles/simple_traffic/etki_facelift.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series XT Passenger', model='simple_traffic', part_config='vehicles/simple_traffic/van_passenger.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Wagon Regulier Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/legran_wagon_facelift_regulier.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 150 Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_eu_base_sedan.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (Old) Street Tuned', model='simple_traffic', part_config='vehicles/simple_traffic/pessima_tuner.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK K-Series kc4 250', model='simple_traffic', part_config='vehicles/simple_traffic/etkc_eu_kc4.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Covet LXi', model='simple_traffic', part_config='vehicles/simple_traffic/covet_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Sedan S Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/legran_sedan_facelift_s.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Roamer V8', model='simple_traffic', part_config='vehicles/simple_traffic/roamer_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril D-Series Cargo Box Upfit', model='simple_traffic', part_config='vehicles/simple_traffic/pickup_d45.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 250 Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_high_sedan.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Sedan Luxe', model='simple_traffic', part_config='vehicles/simple_traffic/legran_sedan_pre_luxe.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (New) DX', model='simple_traffic', part_config='vehicles/simple_traffic/midsize_dx.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Wendover SE 3800 Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/wendover_facelift_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Pessima (New) LX', model='simple_traffic', part_config='vehicles/simple_traffic/midsize_lx.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_wagon_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Base Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_wagon_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril Grand Marshal V8', model='simple_traffic', part_config='vehicles/simple_traffic/fullsize_stock.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Wendover 3300 Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/wendover_facelift_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale SE AWD', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_pre_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series Cargo Box', model='simple_traffic', part_config='vehicles/simple_traffic/van_cargobox.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_wagon_wide.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Base Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_sedan_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale S Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_facelift_mid.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Vivace E', model='simple_traffic', part_config='vehicles/simple_traffic/vivace_ev.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS-Aero Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_sedan_aero.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series XT Passenger Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/van_passenger_facelift.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 150 Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_base_sedan.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Wagon S Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/legran_wagon_facelift_s.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 250 Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_high_wagon.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Ibishu Covet DXi', model='simple_traffic', part_config='vehicles/simple_traffic/covet_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport Sedan', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_sedan_sport.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale S', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_pre_mid.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Tograc 110', model='simple_traffic', part_config='vehicles/simple_traffic/tograc_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale Cargo Van', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_pre_van.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_facelift_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Wendover S 3800', model='simple_traffic', part_config='vehicles/simple_traffic/wendover_pre_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS-Aero Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_eu_wagon_aero.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale SE AWD Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_eu_facelift_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Vivace 160', model='simple_traffic', part_config='vehicles/simple_traffic/vivace_standard.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale SE AWD Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_facelift_high.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell Bastion Base', model='simple_traffic', part_config='vehicles/simple_traffic/bastion_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series Vanster Rapid Delivery', model='simple_traffic', part_config='vehicles/simple_traffic/van_delivery.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Wagon S', model='simple_traffic', part_config='vehicles/simple_traffic/legran_wagon_pre_s.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Gavril H-Series Vanster Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/van_vanster_facelift.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series xc Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_xc.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Hirochi Sunburst Sport RS Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/sunburst2_wagon_wide.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_pre_base.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Wagon SE Facelift', model='simple_traffic', part_config='vehicles/simple_traffic/legran_wagon_facelift_se.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell LeGran Wagon Regulier', model='simple_traffic', part_config='vehicles/simple_traffic/legran_wagon_pre_regulier.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Cherrier Vivace S 270', model='simple_traffic', part_config='vehicles/simple_traffic/vivace_wide.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles ETK 800-Series 150 Wagon', model='simple_traffic', part_config='vehicles/simple_traffic/etk800_eu_base_wagon.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Soliad Lansdale Taxi', model='simple_traffic', part_config='vehicles/simple_traffic/lansdale_pre_taxi.pc', licence='TRAFFIC'),
    Vehicle('(Vehicle) Simplified Traffic Vehicles Bruckell Bastion Luxe', model='simple_traffic', part_config='vehicles/simple_traffic/bastion_luxe.pc', licence='TRAFFIC'),
]