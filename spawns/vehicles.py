from beamngpy import Vehicle
from beamngpy.logging import BNGDisconnectedError, BNGError
import random
import math
from beamngpy import angle_to_quat
from collections import namedtuple
from run.start import scheduler

MIN_SPAWN_SEPARATION_METERS = 20.0
MAX_SPAWN_SEGMENT_ATTEMPTS = 40
MIN_SEGMENT_LENGTH_METERS = 12.0
MIN_SEGMENT_WIDTH_METERS = 2.0
MAX_SEGMENT_WIDTH_METERS = 20.0
MAX_SEGMENT_GRADE_METERS = 4.0
SPAWN_VALIDATION_STEPS = 60
SPAWN_VALIDATION_CHECKS = 2
MAX_SPAWN_DRIFT_METERS = 25.0
MAX_SEGMENT_FAILURES = 3

class builder:
    def __init__(self, simulation):
        self.name = None
        self.simulation = simulation
        self.driver_ref = None
        self.roads = None
        self.spawn_candidates = []
        self.traffic_count = 0
        self.ev_count = 0
        self.accepted_spawn_positions = []
        self.bad_spawn_segments = set()
        self.segment_failure_counts = {}

    def get_road_network(self):
        road_network = self.simulation.beamng.scenario.get_road_network()
        self.roads = []
        self.spawn_candidates = []
        for road_id, road in road_network.items():
            if "edges" not in road or len(road["edges"]) <= 1:
                continue
            road_copy = dict(road)
            road_copy["_road_id"] = road_id
            self.roads.append(road_copy)
            for idx in range(len(road["edges"]) - 1):
                candidate = self._build_spawn_candidate(road_id, road, idx)
                if candidate is not None:
                    self.spawn_candidates.append(candidate)
        self.spawn_candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
        if not self.spawn_candidates:
            raise RuntimeError("No valid road spawn segments were found in the scenario.")

    def _build_spawn_candidate(self, road_id, road, idx):
        points = road["edges"]
        left_start = points[idx]["left"]
        right_start = points[idx]["right"]
        left_end = points[idx + 1]["left"]
        right_end = points[idx + 1]["right"]
        if not all(math.isfinite(v) for v in (*left_start, *right_start, *left_end, *right_end)):
            return None
        width = math.hypot(left_start[0] - right_start[0], left_start[1] - right_start[1])
        if width < MIN_SEGMENT_WIDTH_METERS or width > MAX_SEGMENT_WIDTH_METERS:
            return None
        p1 = (
            (left_start[0] + right_start[0]) * 0.5,
            (left_start[1] + right_start[1]) * 0.5,
            (left_start[2] + right_start[2]) * 0.5,
        )
        p2 = (
            (left_end[0] + right_end[0]) * 0.5,
            (left_end[1] + right_end[1]) * 0.5,
            (left_end[2] + right_end[2]) * 0.5,
        )
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        segment_length = math.hypot(dx, dy)
        if segment_length < MIN_SEGMENT_LENGTH_METERS:
            return None
        grade_delta = abs(p2[2] - p1[2])
        if grade_delta > MAX_SEGMENT_GRADE_METERS:
            return None
        drivability = road.get("drivability")
        if isinstance(drivability, (int, float)) and drivability <= 0:
            return None
        pos = (
            (p1[0] + p2[0]) * 0.5,
            (p1[1] + p2[1]) * 0.5,
            (p1[2] + p2[2]) * 0.5,
        )
        heading = math.degrees(math.atan2(dy, dx))
        score = segment_length + float(drivability or 0.0) - abs(width - 7.0) - (grade_delta * 2.0)
        return {
            "pos": pos,
            "rot_quat": angle_to_quat((0, 0, heading)),
            "segment_key": (road_id, idx),
            "score": score,
        }

    def _is_spawn_position_clear(self, pos):
        min_spacing_sq = MIN_SPAWN_SEPARATION_METERS * MIN_SPAWN_SEPARATION_METERS
        return not any(
            ((pos[0] - accepted[0]) ** 2) + ((pos[1] - accepted[1]) ** 2) + ((pos[2] - accepted[2]) ** 2) < min_spacing_sq
            for accepted in self.accepted_spawn_positions
        )

    def road_random_spawn(self):
        if not self.spawn_candidates:
            raise RuntimeError("No valid roads available for spawning.")
        for candidate in self.spawn_candidates:
            if candidate["segment_key"] in self.bad_spawn_segments:
                continue
            if not self._is_spawn_position_clear(candidate["pos"]):
                continue
            return candidate
        raise RuntimeError("Could not find a valid road spawn segment.")

    def _spawn_state(self, vehicle):
        vehicle.sensors.poll("state")
        state = vehicle.state
        if not isinstance(state, dict):
            raise RuntimeError("vehicle state was unavailable after spawn")
        position = state.get("pos")
        velocity = state.get("vel")
        if position is None or velocity is None:
            raise RuntimeError("spawned vehicle returned incomplete state data")
        if not all(math.isfinite(v) for v in (*position, *velocity)):
            raise RuntimeError("spawned vehicle returned non-finite state data")
        return state

    def _validate_spawn(self, vehicle, spawn):
        try:
            for _ in range(SPAWN_VALIDATION_CHECKS):
                self.simulation.beamng.control.step(SPAWN_VALIDATION_STEPS)
                state = self._spawn_state(vehicle)
                drift = math.dist(state["pos"], spawn["pos"])
                if drift > MAX_SPAWN_DRIFT_METERS:
                    raise RuntimeError(f"spawned vehicle drifted {drift:.1f} m during stabilization")
            return True, None
        except BNGError as e:
            if "request was not handled" in str(e):
                return True, None
            return False, str(e)
        except Exception as e:
            return False, str(e)

    def _record_segment_failure(self, segment_key):
        failures = self.segment_failure_counts.get(segment_key, 0) + 1
        self.segment_failure_counts[segment_key] = failures
        if failures >= MAX_SEGMENT_FAILURES:
            self.bad_spawn_segments.add(segment_key)

    def _reject_spawn(self, vehicle, spawn, reason, bad_segment=True):
        if bad_segment:
            self._record_segment_failure(spawn["segment_key"])
        print(f"Rejected spawn for {vehicle.vid} on {spawn['segment_key']}: {reason}")
        try:
            self.simulation.beamng.vehicles.despawn(vehicle)
        except Exception as e:
            print(f"Failed to despawn rejected vehicle {vehicle.vid}: {e}")
        try:
            vehicle.close()
        except Exception as e:
            print(f"Failed to close rejected vehicle {vehicle.vid}: {e}")

    def vehicle_spawn(self, sound_class=999, control=False):
        match sound_class:
            case 0:
                template = random.choice(FIRE)
                vehicle_vid = template.vid + f" EV_{self.ev_count}"
                self.ev_count += 1
            case 1:
                template = random.choice(POLICE)
                vehicle_vid = template.vid + f" EV_{self.ev_count}"
                self.ev_count += 1
            case 2:
                template = random.choice(AMBULANCE)
                vehicle_vid = template.vid + f" EV_{self.ev_count}"
                self.ev_count += 1
            case _:
                template = random.choice(OTHER)
                vehicle_vid = template.vid + f" TV_{self.traffic_count}"
                self.traffic_count += 1
         
        vehicle_license = template.options.get("licenseText") or template.options.get("license") or template.options.get("licence")
        for attempt in range(MAX_SPAWN_SEGMENT_ATTEMPTS):
            vehicle = Vehicle(
                vid=vehicle_vid if attempt == 0 else f"{vehicle_vid}_{attempt}",
                model=template.options.get("model"),
                part_config=template.options.get("partConfig"),
                licence=vehicle_license,
            )
            try:
                spawn = self.road_random_spawn()
            except RuntimeError as e:
                print(f"Failed to find a spawn point: {e}")
                return None

            spawned = self.simulation.beamng.vehicles.spawn(
                vehicle,
                pos=spawn["pos"],
                rot_quat=spawn["rot_quat"],
                cling=True,
                connect=False,
            )
            if spawned is False:
                self._record_segment_failure(spawn["segment_key"])
                print(f"Failed to spawn vehicle {vehicle.vid}.")
                continue

            try:
                vehicle.connect(self.simulation.beamng)
                self._spawn_state(vehicle)
            except Exception as e:
                self._reject_spawn(vehicle, spawn, f"connection/setup failed: {e}", bad_segment=False)
                continue

            if control:
                viable, reason = self._validate_spawn(vehicle, spawn)
                if not viable:
                    self._reject_spawn(vehicle, spawn, reason)
                    continue

            self.simulation._spawned_vehicles.append(vehicle)
            self.accepted_spawn_positions.append(spawn["pos"])
            veh_ref = Vehicle_Reference(
                vehicle,
                self.simulation.event_scheduler.vehicle_update_tick,
                self.simulation.beamng,
                self.simulation,
                control=control,
            )
            if veh_ref.thread is not None:
                self.simulation.event_scheduler.threads.append(veh_ref.thread)
            return veh_ref

        print(f"Failed to find a viable spawn for {vehicle_vid}.")
        return None

    def driver_presetup(self, ai=True):
        # Driver must have a position before the scenario is loaded and loaded before scenario is made,
        # So therefore I had to extract random positions, getting a better list is ideal
        spawn = self.simulation.environment.random_location()
        driver = random.choice(NORMAL)
        # Store the driver reference
        self.simulation.scenario.add_vehicle(driver, pos=spawn[0], rot_quat=spawn[1], cling=True)
        self.accepted_spawn_positions.append(spawn[0])
        self.driver_ref = Vehicle_Reference(
            driver,
            self.simulation.event_scheduler.vehicle_update_tick,
            self.simulation.beamng,
            self.simulation,
            control=True,
            driver=True,
        )
        if self.driver_ref.thread is not None:
            self.simulation.event_scheduler.threads.append(self.driver_ref.thread)

    def switch_to_driver(self):
        self.simulation.beamng.vehicles.switch(self.driver_ref.vehicle)

    def arm_driver_ai(self, ai=True):
        if not ai:
            return
        if self.driver_ref is None or not getattr(self.driver_ref, "alive", True):
            return

        vehicle = self.driver_ref.vehicle
        self.simulation.beamng.vehicles.switch(vehicle)
        if self.simulation.current_time != "noon":
            vehicle.set_lights(headlights=1)
        vehicle.ai.set_mode("traffic")
        vehicle.ai.set_aggression(0.2)
        vehicle.ai.drive_in_lane(True)
        print("Driver AI armed.")

VehicleState = namedtuple('VehicleState', ['position', 'velocity', 'steering', 'braking', 'damage', 'lane_data'])
class Vehicle_Reference:
    def __init__(self, vehicle, tick, beamng, simulation, control=False, driver=False):
        self.vehicle = vehicle
        self.tick = tick
        self.beamng = beamng
        self.simulation = simulation
        self.vid = vehicle.vid
        self.thread = None
        self.alive = True
        self.controlled = control
        self.driver = driver
        
        self.state = VehicleState((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0, 0.0, 0.0, (0.0, 0.0, 0.0, 0.0))
        self.state_available = False

        if control:
            if driver:
                print(f"Driver vehicle {self.vid} initialized")
                self.thread = scheduler.start_guarded_thread(self.simulation, self.driver_run, f"Driver control thread {self.vid}")
            else:
                print(f"Sound event vehicle {self.vid} initialized")
                self.thread = scheduler.start_guarded_thread(self.simulation, self.run, f"Vehicle control thread {self.vid}")

    def run(self):
        self.tick.waited_action()
        self.tick.waited_action_iterate(self.update, cond_func=lambda: self.alive)

    def driver_run(self):
        self.tick.waited_action()
        self.tick.waited_action_iterate(self.update, cond_func=lambda: self.alive)

    def _read_state(self):
        self.vehicle.sensors.poll("state")
        state = self.vehicle.state
        position = state.get("pos")  
        velocity = state.get("vel")    
        return position, velocity
 
    def update(self):
        if not self.alive:
            return    
        try:
            position, velocity = self._read_state()
            self.state_available = True
            self.state = VehicleState(position, velocity, 0.0, 0.0, 0.0, (0.0, 0.0, 0.0, 0.0))
            
        except Exception as e:
            self.state_available = False
            
            # Fatal socket disconnect: Invalidate the trial directly and kill thread
            if "connect" in str(e).lower() or "not connected" in str(e).lower():
                self.alive = False
                self.simulation.invalidate_trial(f"Vehicle {self.vid} disconnected: {e}", stop_run=True)


POLICE = [
    Vehicle('(Vehicle) Hopper Sheriff (M)', model='hopper', part_config='vehicles/hopper/sheriff.pc', licence='EV'),
    Vehicle('(Vehicle) Pessima Police (A)', model='midsize', part_config='vehicles/midsize/police.pc', licence='EV'),
    Vehicle('(Vehicle) Covet Police (A)', model='covet', part_config='vehicles/covet/police.pc', licence='EV'),
    Vehicle('(Vehicle) Wendover Police Interceptor (A)', model='wendover', part_config='vehicles/wendover/interceptor.pc', licence='EV'),
    Vehicle('(Vehicle) Bluebuck Police Package (A)', model='bluebuck', part_config='vehicles/bluebuck/police.pc', licence='EV'),
    Vehicle('(Vehicle) Bluebuck Police Interceptor (A)', model='bluebuck', part_config='vehicles/bluebuck/interceptor.pc', licence='EV'),
    Vehicle('(Vehicle) Special 313 V8 4-Door Sedan Police Package (A)', model='burnside', part_config='vehicles/burnside/4door_late_v8_3A_police.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer Belasco City Police Department (A)', model='roamer', part_config='vehicles/roamer/police.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer LXT35 Police Package (Unmarked) (A)', model='roamer', part_config='vehicles/roamer/unmarked.pc', licence='EV'),
    Vehicle('(Vehicle) Roamer Sheriff (A)', model='roamer', part_config='vehicles/roamer/sheriff.pc', licence='EV'),
    Vehicle('(Vehicle) MD-Series MD60 Armored Police (M)', model='md_series', part_config='vehicles/md_series/md_60_armored_police.pc', licence='EV'),
    Vehicle('(Vehicle) Bastion Police (Unmarked) 5.7 AWD (A)', model='bastion', part_config='vehicles/bastion/police_unmarked_v8_awd_A.pc', licence='EV'),
    Vehicle('(Vehicle) Bastion Police 5.7 AWD (A)', model='bastion', part_config='vehicles/bastion/police_v8_awd_A.pc', licence='EV'),
    Vehicle('(Vehicle) Grand Marshal Belasco City Police Department (A)', model='fullsize', part_config='vehicles/fullsize/bcpd.pc', licence='EV'),
    Vehicle('(Vehicle) Grand Marshal Police Package (Unmarked) (A)', model='fullsize', part_config='vehicles/fullsize/unmarked.pc', licence='EV'),
    Vehicle('(Vehicle) Grand Marshal Police Package (A)', model='fullsize', part_config='vehicles/fullsize/police.pc', licence='EV'),
    Vehicle('(Vehicle) Sunburst Police Package (CVT)', model='sunburst2', part_config='vehicles/sunburst2/police.pc', licence='EV'),
    Vehicle('(Vehicle) Sunburst Police Interceptor (DCT)', model='sunburst2', part_config='vehicles/sunburst2/interceptor.pc', licence='EV'),
    Vehicle('(Vehicle) Lansdale 3.3 S Police (A)', model='lansdale', part_config='vehicles/lansdale/33_police_late_A.pc', licence='EV'),
]

AMBULANCE = [
    Vehicle('(Vehicle) D-Series D45 Off-Road Ambulance (A)', model='pickup', part_config='vehicles/pickup/d45_diesel_4wd_ambulance_A.pc', licence='EV'),
    Vehicle('(Vehicle) MD-Series MD70 Ambulance 4WD (M)', model='md_series', part_config='vehicles/md_series/md_70_ambulance_4wd.pc', licence='EV'),
    Vehicle('(Vehicle) MD-Series MD60 Ambulance (A)', model='md_series', part_config='vehicles/md_series/md_60_ambulance.pc', licence='EV'),
    Vehicle('(Vehicle) D-Series D45 Ambulance (A)', model='pickup', part_config='vehicles/pickup/d45_ambulance_A.pc', licence='EV'),
]

FIRE = [
    Vehicle("(Vehicle) Stambecco Stambecco 525-FP (M)", model="midtruck", part_config="vehicles/midtruck/6x6_firetruck_petrol.pc", licence="EV"),
    Vehicle("(Vehicle) Stambecco Stambecco 525-FP-2 (M)", model="midtruck", part_config="vehicles/midtruck/6x6_firetruck_diesel.pc", licence="EV"),
    Vehicle("(Vehicle) Roamer Roamer Fire Chief (A)", model="roamer", part_config="vehicles/roamer/firechief.pc", licence="EV"),
    Vehicle("(Vehicle) LeGran LeGran Fire Chief (Facelift) (A)", model="legran", part_config="vehicles/legran/firechief.pc", licence="EV"),
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
