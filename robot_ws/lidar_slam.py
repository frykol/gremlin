"""
Minimalny SLAM oparty wylacznie na lidarze L1 (bez odometrii, bez loop
closure): kolejne "ramki" chmury punktow sa rejestrowane metoda ICP wzgledem
dotychczasowej mapy, zeby oszacowac ruch czujnika, po czym punkty ramki
trafiaja (po transformacji do ukladu globalnego) do rosnacej mapy.

Ograniczenia (swiadomie, na start):
- brak loop closure -> dryf pozycji rosnie z dystansem/czasem
- brak zewnetrznej odometrii -> ICP to jedyne zrodlo ruchu, wrazliwe na
  otoczenie bez wyraznych cech geometrycznych (puste korytarze itp.)
- ICP punkt-do-punktu (bez normalnych) - prostsze, wolniejsze do zbieznosci
  niz punkt-do-plaszczyzny, ale nie wymaga estymacji normalnych w locie

Uzycie:
    python3 lidar_slam.py --port /dev/ttyUSB0 --seconds 30 \
        --map-out map.csv --traj-out trajectory.csv
"""
import argparse
import csv
import math
import sys
import time
from collections import deque

import numpy as np
from scipy.spatial import cKDTree

from lidar_live_capture import (
    iter_mavlink_frames,
    parse_distance_packet,
    parse_auxiliary_packet,
    range_aux_to_cloud,
    DIST_LEN,
    AUX_LEN,
)

import json

from wheel_odometry_reader import WheelOdometryReader

import serial


def icp(source, target_tree, target_points, max_iters=25, tol=1e-5, max_corr_dist=0.5):
    """Point-to-point ICP. source: Nx3 punkty do dopasowania (w ukladzie
    lokalnym ramki, juz z poczatkowym oszacowaniem R,t naniesionym przez
    wywolujacego). Zwraca (R,t,fitness) - poprawke wzgledem wejscia."""
    R = np.eye(3)
    t = np.zeros(3)
    prev_err = None
    pts = source.copy()

    for _ in range(max_iters):
        dists, idx = target_tree.query(pts, k=1)
        mask = dists < max_corr_dist
        if mask.sum() < 20:
            break
        src_m = pts[mask]
        dst_m = target_points[idx[mask]]

        src_c = src_m.mean(axis=0)
        dst_c = dst_m.mean(axis=0)
        H = (src_m - src_c).T @ (dst_m - dst_c)
        U, _, Vt = np.linalg.svd(H)
        Ri = Vt.T @ U.T
        if np.linalg.det(Ri) < 0:
            Vt[-1, :] *= -1
            Ri = Vt.T @ U.T
        ti = dst_c - Ri @ src_c

        pts = (Ri @ pts.T).T + ti
        R = Ri @ R
        t = Ri @ t + ti

        err = float(np.mean(dists[mask]))
        if prev_err is not None and abs(prev_err - err) < tol:
            break
        prev_err = err

    fitness = mask.sum() / max(1, len(pts)) if mask is not None else 0.0
    return R, t, fitness


def voxel_downsample(points, voxel_size):
    if len(points) == 0:
        return points
    keys = np.floor(points[:, :3] / voxel_size).astype(np.int64)
    _, unique_idx = np.unique(keys, axis=0, return_index=True)
    return points[unique_idx]


class LidarSlam:
    def __init__(self, voxel_size=0.06, map_cap=200_000, frame_window=0.2,
                 min_fitness=0.6, max_speed=1.5, use_icp=True):
        self.voxel_size = voxel_size
        self.map_cap = map_cap
        self.frame_window = frame_window
        self.min_fitness = min_fitness
        # Maksymalna wiarygodna predkosc [m/s] - jesli ICP oszacuje wiekszy
        # przeskok niz to na dane okno czasowe, traktujemy to jako zle
        # dopasowanie (bledny lokalny minimum), a nie realny ruch.
        self.max_speed = max_speed
        # Gdy False: zadnej rejestracji, surowa akumulacja klatek w ukladzie
        # czujnika (identity transform). Sensowne dopoki lidar faktycznie
        # sie nie porusza - ICP na stacjonarnym skanerze tylko wprowadza
        # falszywe mikro-przesuniecia (plaskie sciany sa niejednoznaczne
        # geometrycznie), ktore rozmywaja ostre powierzchnie w szum.
        self.use_icp = use_icp

        self.map_xyz = np.empty((0, 3))
        self.map_intensity = np.empty((0,))
        self.pose_R = np.eye(3)
        self.pose_t = np.zeros(3)
        self.trajectory = [(0.0, 0.0, 0.0, 0.0)]  # t, x, y, z
        self._tree = None
        self.rejected_frames = 0

    def _rebuild_tree(self):
        self._tree = cKDTree(self.map_xyz) if len(self.map_xyz) > 0 else None

    def add_frame(self, frame_xyz, frame_intensity, t_stamp, odom_delta=None):
        if len(frame_xyz) < 30:
            return "too_small"  # zbyt maly fragment, pomijamy (szum/brak echa)

        if len(self.map_xyz) == 0 or not self.use_icp:
            # Pierwsza ramka definiuje poczatek ukladu globalnego, albo
            # SLAM dziala w trybie bez rejestracji (--no-icp).
            global_pts = (self.pose_R @ frame_xyz.T).T + self.pose_t
        else:
            if self._tree is None:
                self._rebuild_tree()

            if odom_delta is not None:
                dR_odom, dt_odom = odom_delta
                guess_R = dR_odom @ self.pose_R
                guess_t = dR_odom @ self.pose_t + dt_odom
            else:
                # Brak swiezych danych o ruchu z kol - zakladamy brak ruchu
                # wzgledem ostatniej pozy (jak dotychczas).
                guess_R = self.pose_R
                guess_t = self.pose_t

            guess = (guess_R @ frame_xyz.T).T + guess_t
            dR, dt, fitness = icp(guess, self._tree, self.map_xyz)

            new_pose_R = dR @ guess_R
            new_pose_t = dR @ guess_t + dt

            if odom_delta is not None:
                # Silniejszy sanity check niz sztywny limit predkosci:
                # porownaj wynik ICP z tym, co przewidziala odometria z
                # kol - wykrywa tez sytuacje gdy ICP "zjechal" w zle
                # lokalne minimum mimo wiarygodnej predkosci.
                odom_predicted_t = dR_odom @ self.pose_t + dt_odom
                divergence = float(np.linalg.norm(new_pose_t - odom_predicted_t))
                # Kola napedzane PWM bez enkoderow - predkosc maksymalna jest
                # kalibrowana jednorazowo recznie, stoperem (patrz
                # calibrate_wheel_speed.py), wiec odometria kolowa jest z
                # natury szumiaca/przyblizona. Tolerancja jest wiec celowo
                # szeroka: 50% przewidywanego dystansu przejazdu + staly
                # margines 10cm dla ruchu bliskiego zeru (zeby male szumy przy
                # postoju nie wywalaly klatek). To inna filozofia niz stary,
                # sztywny limit --max-speed, ktory ogranicza bezwzgledne
                # przemieszczenie na klatke - tutaj ograniczamy zgodnosc
                # miedzy dwoma niezaleznymi estymatorami ruchu (ICP vs kola),
                # niezaleznie od tego jak duzy byl sam ruch.
                max_divergence = max(0.1, float(np.linalg.norm(dt_odom)) * 0.5 + 0.05)
                reject = fitness < self.min_fitness or divergence > max_divergence
            else:
                step_translation = float(np.linalg.norm(new_pose_t - self.pose_t))
                max_step = self.max_speed * self.frame_window
                reject = fitness < self.min_fitness or step_translation > max_step

            if reject:
                self.rejected_frames += 1
                self.trajectory.append((t_stamp, *self.pose_t.tolist()))
                return "rejected"

            self.pose_R = new_pose_R
            self.pose_t = new_pose_t
            global_pts = (self.pose_R @ frame_xyz.T).T + self.pose_t

        self.map_xyz = np.vstack([self.map_xyz, global_pts])
        self.map_intensity = np.concatenate([self.map_intensity, frame_intensity])

        if len(self.map_xyz) > self.map_cap:
            ds = voxel_downsample(
                np.hstack([self.map_xyz, self.map_intensity[:, None]]), self.voxel_size
            )
            self.map_xyz, self.map_intensity = ds[:, :3], ds[:, 3]

        self._rebuild_tree()
        self.trajectory.append((t_stamp, *self.pose_t.tolist()))
        return "ok"


class WheelCalibrationError(Exception):
    """Podniesione gdy plik kalibracji kol jest brakujacy lub niepoprawny."""


def load_wheel_calibration(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return float(data["max_wheel_speed_rad_s"])
    except FileNotFoundError as exc:
        raise WheelCalibrationError(
            f"wheel calibration file '{path}' is missing or invalid. "
            "Run robot_ws/calibrate_wheel_speed.py first (see robot_ws/README.md Task 5) "
            "and write its output to this file before using --odom-state-file."
        ) from exc
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise WheelCalibrationError(
            f"wheel calibration file '{path}' is missing or invalid. "
            "Run robot_ws/calibrate_wheel_speed.py first (see robot_ws/README.md Task 5) "
            "and write its output to this file before using --odom-state-file."
        ) from exc


def main():
    ap = argparse.ArgumentParser(description="Lidar-only SLAM (ICP scan-to-map, bez loop closure)")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=2_000_000)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--frame-window", type=float, default=0.2, help="okno czasowe [s] grupujace punkty w jedna ramke ICP")
    ap.add_argument("--voxel-size", type=float, default=0.06, help="rozdzielczosc mapy [m] przy przycinaniu")
    ap.add_argument("--map-cap", type=int, default=200_000)
    ap.add_argument(
        "--min-intensity", type=float, default=20.0,
        help="odrzuc punkty ze slabym odbiciem (0-255) - male odbicie to zwykle szum/niepewny pomiar, nie ma sensu wciagac go do mapy",
    )
    ap.add_argument(
        "--min-fitness", type=float, default=0.6,
        help="minimalny udzial dopasowanych punktow ICP, ponizej ktorego ramka jest odrzucana (zle dopasowanie)",
    )
    ap.add_argument(
        "--max-speed", type=float, default=1.5,
        help="maksymalna wiarygodna predkosc [m/s] - wiekszy skok pozycji miedzy ramkami = odrzucenie ramki",
    )
    ap.add_argument(
        "--no-icp", action="store_true",
        help="wylacz rejestracje ICP, surowa akumulacja klatek (sensowne dla stacjonarnego czujnika / testu bazowego)",
    )
    ap.add_argument(
        "--odom-state-file", default=None,
        help="sciezka do pliku stanu kol pisanego przez CommandProcessor.write_wheel_state() (np. /tmp/wheel_state.json) - gdy podane, ICP dostaje initial guess z odometrii kolowej zamiast zakladac brak ruchu",
    )
    ap.add_argument(
        "--wheel-calibration", default="wheel_calibration.json",
        help="plik JSON z zmierzona stala {'max_wheel_speed_rad_s': ...} - wymagany gdy podano --odom-state-file",
    )
    ap.add_argument("--map-out", default="map.csv")
    ap.add_argument("--traj-out", default="trajectory.csv")
    args = ap.parse_args()

    odom_reader = None
    if args.odom_state_file:
        try:
            max_wheel_speed = load_wheel_calibration(args.wheel_calibration)
        except WheelCalibrationError as exc:
            ap.error(
                f"--odom-state-file was given but {exc}"
            )
        odom_reader = WheelOdometryReader(args.odom_state_file, max_wheel_speed)

    ser = serial.Serial(args.port, args.baud, timeout=0)
    print(f"Otwarty {args.port} @ {args.baud}, SLAM przez {args.seconds}s...", file=sys.stderr)

    slam = LidarSlam(
        voxel_size=args.voxel_size, map_cap=args.map_cap, frame_window=args.frame_window,
        min_fitness=args.min_fitness, max_speed=args.max_speed, use_icp=not args.no_icp,
    )

    buf = bytearray()
    pending_dist, pending_aux = {}, {}
    frame_pts, frame_int = [], []
    t_start = time.time()
    t_frame_start = t_start
    t_end = t_start + args.seconds

    try:
        while time.time() < t_end:
            chunk = ser.read(1024 * 64)
            if chunk:
                buf.extend(chunk)
                frames, buf = iter_mavlink_frames(buf)
                for msgid, payload in frames:
                    pid = None
                    if msgid == 16 and len(payload) == DIST_LEN:
                        d = parse_distance_packet(payload)
                        pending_dist[d["packet_id"]] = d
                        pid = d["packet_id"]
                    elif msgid == 17 and len(payload) == AUX_LEN:
                        a = parse_auxiliary_packet(payload)
                        pending_aux[a["packet_id"]] = a
                        pid = a["packet_id"]

                    if pid is not None and pid in pending_dist and pid in pending_aux:
                        for x, y, z, intensity in range_aux_to_cloud(pending_aux.pop(pid), pending_dist.pop(pid)):
                            if intensity < args.min_intensity:
                                continue  # slabe odbicie - szum/niepewny pomiar, pomijamy przy budowie mapy
                            frame_pts.append((x, y, z))
                            frame_int.append(intensity)
            else:
                time.sleep(0.002)

            now = time.time()
            if now - t_frame_start >= args.frame_window and frame_pts:
                odom_delta = odom_reader.poll_delta() if odom_reader is not None else None
                slam.add_frame(
                    np.array(frame_pts, dtype=np.float64),
                    np.array(frame_int, dtype=np.float64),
                    now - t_start,
                    odom_delta=odom_delta,
                )
                frame_pts, frame_int = [], []
                t_frame_start = now
                print(
                    f"\rmapa={len(slam.map_xyz)} pkt | pozycja=({slam.pose_t[0]:+.2f},{slam.pose_t[1]:+.2f},{slam.pose_t[2]:+.2f}) m",
                    end="", file=sys.stderr,
                )
    finally:
        ser.close()

    print(file=sys.stderr)
    with open(args.map_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["x", "y", "z", "intensity"])
        for (x, y, z), i in zip(slam.map_xyz, slam.map_intensity):
            w.writerow([x, y, z, i])
    print(f"Zapisano mape: {args.map_out} ({len(slam.map_xyz)} punktow, odrzuconych ramek={slam.rejected_frames})", file=sys.stderr)

    with open(args.traj_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "x", "y", "z"])
        w.writerows(slam.trajectory)
    print(f"Zapisano trajektorie: {args.traj_out} ({len(slam.trajectory)} pozycji)", file=sys.stderr)


if __name__ == "__main__":
    main()
