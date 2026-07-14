#include "unitree_lidar_sdk.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <iostream>
#include <limits>
#include <poll.h>
#include <sstream>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

using namespace unitree_lidar_sdk;
using Clock = std::chrono::steady_clock;

namespace {
std::atomic_bool keep_running{true};

void handleSignal(int) {
    keep_running = false;
}

bool stdinReady() {
    pollfd descriptor{};
    descriptor.fd = STDIN_FILENO;
    descriptor.events = POLLIN;
    return ::poll(&descriptor, 1, 0) > 0 && (descriptor.revents & POLLIN);
}

std::string lowerCopy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

void printHelp() {
    std::cout
        << "\nKomendy (zatwierdz Enterem):\n"
        << "  start / s             - tryb NORMAL: silniki i pomiar punktow wlaczone\n"
        << "  stop / x              - tryb STANDBY: silniki i punkty zatrzymane, IMU dziala\n"
        << "  cycle / c             - STANDBY na 3 sekundy, potem NORMAL\n"
        << "  autotest / t          - automatyczny test NORMAL -> STANDBY -> NORMAL\n"
        << "  reset / r             - reset LiDAR-u\n"
        << "  info / i              - wersje, zabrudzenie i opoznienie transmisji\n"
        << "  status                - natychmiast pokaz aktualny stan danych\n"
        << "  points [N]            - pokaz N pierwszych punktow ostatniej chmury (domyslnie 10)\n"
        << "  imu                    - pokaz ostatnie dane IMU\n"
        << "  snapshot [plik.csv]   - zapisz ostatnia chmure punktow do CSV\n"
        << "  led off|on|slow|fast|reverse|breath\n"
        << "  clear                  - wyzeruj statystyki\n"
        << "  help / h               - pokaz pomoc\n"
        << "  quit / q               - zakoncz program\n\n";
}

struct Statistics {
    std::uint64_t clouds_total = 0;
    std::uint64_t points_total = 0;
    std::uint64_t imu_total = 0;
    std::uint64_t auxiliary_total = 0;
    std::uint64_t version_total = 0;

    std::uint64_t clouds_window = 0;
    std::uint64_t points_window = 0;
    std::uint64_t imu_window = 0;

    std::size_t last_cloud_points = 0;
    std::size_t last_valid_points = 0;
    double last_min_distance = 0.0;
    double last_mean_distance = 0.0;
    double last_max_distance = 0.0;
    double last_mean_intensity = 0.0;
    PointUnitree nearest_point{};
    bool has_nearest_point = false;

    PointCloudUnitree last_cloud{};
    IMUUnitree last_imu{};
    bool has_cloud = false;
    bool has_imu = false;

    Clock::time_point started = Clock::now();
    Clock::time_point window_started = Clock::now();
    Clock::time_point last_cloud_at{};
    Clock::time_point last_imu_at{};

    void clear() {
        *this = Statistics{};
    }
};

void updateCloudStats(const PointCloudUnitree& cloud, Statistics& stats) {
    stats.clouds_total++;
    stats.clouds_window++;
    stats.points_total += cloud.points.size();
    stats.points_window += cloud.points.size();
    stats.last_cloud_points = cloud.points.size();
    stats.last_cloud_at = Clock::now();
    stats.last_cloud = cloud;
    stats.has_cloud = true;

    double min_distance = std::numeric_limits<double>::infinity();
    double max_distance = 0.0;
    double distance_sum = 0.0;
    double intensity_sum = 0.0;
    std::size_t valid_points = 0;
    PointUnitree nearest{};

    for (const auto& point : cloud.points) {
        const double x = static_cast<double>(point.x);
        const double y = static_cast<double>(point.y);
        const double z = static_cast<double>(point.z);
        const double distance = std::sqrt(x * x + y * y + z * z);

        if (!std::isfinite(distance) || distance <= 0.0) {
            continue;
        }

        if (distance < min_distance) {
            min_distance = distance;
            nearest = point;
        }
        max_distance = std::max(max_distance, distance);
        distance_sum += distance;
        intensity_sum += static_cast<double>(point.intensity);
        valid_points++;
    }

    stats.last_valid_points = valid_points;
    if (valid_points == 0) {
        stats.last_min_distance = 0.0;
        stats.last_mean_distance = 0.0;
        stats.last_max_distance = 0.0;
        stats.last_mean_intensity = 0.0;
        stats.has_nearest_point = false;
        return;
    }

    stats.last_min_distance = min_distance;
    stats.last_mean_distance = distance_sum / static_cast<double>(valid_points);
    stats.last_max_distance = max_distance;
    stats.last_mean_intensity = intensity_sum / static_cast<double>(valid_points);
    stats.nearest_point = nearest;
    stats.has_nearest_point = true;
}

void updateImuStats(const IMUUnitree& imu, Statistics& stats) {
    stats.imu_total++;
    stats.imu_window++;
    stats.last_imu = imu;
    stats.has_imu = true;
    stats.last_imu_at = Clock::now();
}

struct WindowRates {
    double cloud_hz = 0.0;
    double points_per_second = 0.0;
    double imu_hz = 0.0;
};

WindowRates calculateRates(const Statistics& stats, Clock::time_point now) {
    const double seconds = std::chrono::duration<double>(now - stats.window_started).count();
    WindowRates rates;
    if (seconds > 0.0) {
        rates.cloud_hz = static_cast<double>(stats.clouds_window) / seconds;
        rates.points_per_second = static_cast<double>(stats.points_window) / seconds;
        rates.imu_hz = static_cast<double>(stats.imu_window) / seconds;
    }
    return rates;
}

void resetWindow(Statistics& stats, Clock::time_point now) {
    stats.clouds_window = 0;
    stats.points_window = 0;
    stats.imu_window = 0;
    stats.window_started = now;
}

void printStatus(Statistics& stats, bool reset_window = true) {
    const auto now = Clock::now();
    const WindowRates rates = calculateRates(stats, now);

    double cloud_age = -1.0;
    if (stats.last_cloud_at.time_since_epoch().count() != 0) {
        cloud_age = std::chrono::duration<double>(now - stats.last_cloud_at).count();
    }

    double imu_age = -1.0;
    if (stats.last_imu_at.time_since_epoch().count() != 0) {
        imu_age = std::chrono::duration<double>(now - stats.last_imu_at).count();
    }

    const bool cloud_fresh = cloud_age >= 0.0 && cloud_age < 2.0;
    const bool detects_points = cloud_fresh && stats.last_valid_points > 0;

    std::cout << std::fixed << std::setprecision(2)
              << (detects_points ? "[OK: WYKRYWA PUNKTY] " : "[BRAK SWIEZYCH PUNKTOW] ")
              << "chmury=" << rates.cloud_hz << " Hz"
              << " | punkty=" << rates.points_per_second << "/s"
              << " | ostatnia=" << stats.last_valid_points << "/" << stats.last_cloud_points
              << " | dystans min/sr/max="
              << stats.last_min_distance << "/"
              << stats.last_mean_distance << "/"
              << stats.last_max_distance << " m"
              << " | IMU=" << rates.imu_hz << " Hz";

    if (cloud_age >= 0.0) {
        std::cout << " | wiek chmury=" << cloud_age << " s";
    }
    if (imu_age >= 0.0) {
        std::cout << " | wiek IMU=" << imu_age << " s";
    }
    std::cout << '\n';

    if (stats.has_nearest_point && detects_points) {
        std::cout << "    najblizszy punkt xyz=["
                  << stats.nearest_point.x << ", "
                  << stats.nearest_point.y << ", "
                  << stats.nearest_point.z << "] m"
                  << " | intensity=" << stats.nearest_point.intensity
                  << " | srednia intensity=" << stats.last_mean_intensity << '\n';
    }

    if (reset_window) {
        resetWindow(stats, now);
    }
}

void printInfo(UnitreeLidarReader* reader, const Statistics& stats) {
    std::string firmware = reader->getVersionOfFirmware();
    if (firmware.empty()) {
        firmware = "jeszcze nie odebrano pakietu VERSION";
    }

    std::cout << "SDK: " << reader->getVersionOfSDK()
              << " | firmware: " << firmware << '\n'
              << "Zabrudzenie/odrzucone punkty: " << std::fixed << std::setprecision(2)
              << reader->getDirtyPercentage() << " %\n"
              << "Opoznienie transmisji: " << reader->getTimeDelay() << " us\n"
              << "Laczniki od startu: chmury=" << stats.clouds_total
              << ", punkty=" << stats.points_total
              << ", IMU=" << stats.imu_total
              << ", AUX=" << stats.auxiliary_total
              << ", VERSION=" << stats.version_total << '\n';
}

void printPoints(const Statistics& stats, std::size_t requested) {
    if (!stats.has_cloud || stats.last_cloud.points.empty()) {
        std::cout << "Brak chmury punktow do wyswietlenia.\n";
        return;
    }

    const std::size_t count = std::min(requested, stats.last_cloud.points.size());
    std::cout << "Pierwsze " << count << " punktow ostatniej chmury:\n";
    std::cout << "  #       x        y        z      dist   intensity   time      ring\n";

    for (std::size_t i = 0; i < count; ++i) {
        const auto& point = stats.last_cloud.points[i];
        const double distance = std::sqrt(
            static_cast<double>(point.x) * point.x +
            static_cast<double>(point.y) * point.y +
            static_cast<double>(point.z) * point.z);

        std::cout << std::fixed << std::setprecision(4)
                  << std::setw(3) << i << "  "
                  << std::setw(8) << point.x << " "
                  << std::setw(8) << point.y << " "
                  << std::setw(8) << point.z << " "
                  << std::setw(8) << distance << " "
                  << std::setw(9) << point.intensity << " "
                  << std::setw(8) << point.time << " "
                  << point.ring << '\n';
    }
}

void printImu(const Statistics& stats) {
    if (!stats.has_imu) {
        std::cout << "Nie odebrano jeszcze danych IMU.\n";
        return;
    }

    const auto& imu = stats.last_imu;
    std::cout << std::fixed << std::setprecision(5)
              << "IMU id=" << imu.id << " stamp=" << imu.stamp << '\n'
              << "  quaternion [x,y,z,w] = ["
              << imu.quaternion[0] << ", " << imu.quaternion[1] << ", "
              << imu.quaternion[2] << ", " << imu.quaternion[3] << "]\n"
              << "  angular velocity     = ["
              << imu.angular_velocity[0] << ", " << imu.angular_velocity[1] << ", "
              << imu.angular_velocity[2] << "]\n"
              << "  linear acceleration  = ["
              << imu.linear_acceleration[0] << ", " << imu.linear_acceleration[1] << ", "
              << imu.linear_acceleration[2] << "]\n";
}

std::string defaultSnapshotName() {
    const std::time_t now = std::time(nullptr);
    std::tm local{};
    localtime_r(&now, &local);
    char buffer[64]{};
    std::strftime(buffer, sizeof(buffer), "lidar_l1_snapshot_%Y%m%d_%H%M%S.csv", &local);
    return buffer;
}

bool saveSnapshot(const Statistics& stats, const std::string& filename) {
    if (!stats.has_cloud || stats.last_cloud.points.empty()) {
        std::cout << "Brak chmury punktow do zapisania.\n";
        return false;
    }

    std::ofstream output(filename);
    if (!output) {
        std::cerr << "Nie mozna utworzyc pliku: " << filename << '\n';
        return false;
    }

    output << "cloud_stamp,cloud_id,x,y,z,distance,intensity,relative_time,ring\n";
    output << std::setprecision(9);
    for (const auto& point : stats.last_cloud.points) {
        const double distance = std::sqrt(
            static_cast<double>(point.x) * point.x +
            static_cast<double>(point.y) * point.y +
            static_cast<double>(point.z) * point.z);
        output << stats.last_cloud.stamp << ','
               << stats.last_cloud.id << ','
               << point.x << ',' << point.y << ',' << point.z << ','
               << distance << ',' << point.intensity << ','
               << point.time << ',' << point.ring << '\n';
    }

    std::cout << "Zapisano " << stats.last_cloud.points.size()
              << " punktow do: " << filename << '\n';
    return true;
}

void setLed(UnitreeLidarReader* reader, const std::string& mode) {
    if (mode == "off") {
        uint8_t table[45]{};
        reader->setLEDDisplayMode(table);
        std::cout << "LED: wszystkie wylaczone.\n";
    } else if (mode == "on") {
        uint8_t table[45];
        std::fill(std::begin(table), std::end(table), static_cast<uint8_t>(0xFF));
        reader->setLEDDisplayMode(table);
        std::cout << "LED: wszystkie wlaczone.\n";
    } else if (mode == "slow") {
        reader->setLEDDisplayMode(FORWARD_SLOW);
        std::cout << "LED: wolno do przodu.\n";
    } else if (mode == "fast") {
        reader->setLEDDisplayMode(FORWARD_FAST);
        std::cout << "LED: szybko do przodu.\n";
    } else if (mode == "reverse") {
        reader->setLEDDisplayMode(REVERSE_SLOW);
        std::cout << "LED: wolno wstecz.\n";
    } else if (mode == "breath") {
        reader->setLEDDisplayMode(SIXSTAGE_BREATHING);
        std::cout << "LED: oddychanie szesciostopniowe.\n";
    } else {
        std::cout << "Uzycie: led off|on|slow|fast|reverse|breath\n";
    }
}

enum class AutoTestPhase {
    Idle,
    Normal,
    Standby,
    Resume
};

struct AutoTest {
    AutoTestPhase phase = AutoTestPhase::Idle;
    Clock::time_point deadline{};
    std::uint64_t baseline_clouds = 0;
    std::uint64_t baseline_points = 0;
    std::uint64_t baseline_imu = 0;
    std::uint64_t normal_clouds = 0;
    std::uint64_t normal_points = 0;
    std::uint64_t standby_clouds = 0;
    std::uint64_t standby_imu = 0;
    std::uint64_t resume_clouds = 0;
    std::uint64_t resume_points = 0;
    bool exit_after = false;

    bool active() const {
        return phase != AutoTestPhase::Idle;
    }
};

void startAutoTest(UnitreeLidarReader* reader, const Statistics& stats,
                   AutoTest& test, bool exit_after) {
    std::cout << "\n[AUTOTEST] Etap 1/3: NORMAL przez 5 sekund.\n";
    reader->setLidarWorkingMode(NORMAL);
    test = AutoTest{};
    test.phase = AutoTestPhase::Normal;
    test.deadline = Clock::now() + std::chrono::seconds(5);
    test.baseline_clouds = stats.clouds_total;
    test.baseline_points = stats.points_total;
    test.baseline_imu = stats.imu_total;
    test.exit_after = exit_after;
}

bool updateAutoTest(UnitreeLidarReader* reader, const Statistics& stats, AutoTest& test) {
    if (!test.active() || Clock::now() < test.deadline) {
        return false;
    }

    if (test.phase == AutoTestPhase::Normal) {
        test.normal_clouds = stats.clouds_total - test.baseline_clouds;
        test.normal_points = stats.points_total - test.baseline_points;

        std::cout << "[AUTOTEST] NORMAL: chmury=" << test.normal_clouds
                  << ", punkty=" << test.normal_points << '\n'
                  << "[AUTOTEST] Etap 2/3: STANDBY przez 4 sekundy.\n";

        reader->setLidarWorkingMode(STANDBY);
        test.phase = AutoTestPhase::Standby;
        test.deadline = Clock::now() + std::chrono::seconds(4);
        test.baseline_clouds = stats.clouds_total;
        test.baseline_imu = stats.imu_total;
        return false;
    }

    if (test.phase == AutoTestPhase::Standby) {
        test.standby_clouds = stats.clouds_total - test.baseline_clouds;
        test.standby_imu = stats.imu_total - test.baseline_imu;

        std::cout << "[AUTOTEST] STANDBY: nowe chmury=" << test.standby_clouds
                  << ", pakiety IMU=" << test.standby_imu << '\n'
                  << "[AUTOTEST] Etap 3/3: ponowny NORMAL przez 6 sekund.\n";

        reader->setLidarWorkingMode(NORMAL);
        test.phase = AutoTestPhase::Resume;
        test.deadline = Clock::now() + std::chrono::seconds(6);
        test.baseline_clouds = stats.clouds_total;
        test.baseline_points = stats.points_total;
        return false;
    }

    test.resume_clouds = stats.clouds_total - test.baseline_clouds;
    test.resume_points = stats.points_total - test.baseline_points;

    const bool normal_ok = test.normal_clouds > 0 && test.normal_points > 0;
    // Po zmianie trybu moze dojsc jedna-dwie juz zbuforowane chmury.
    const bool standby_ok = test.standby_clouds <= 2 && test.standby_imu > 0;
    const bool resume_ok = test.resume_clouds > 0 && test.resume_points > 0;
    const bool passed = normal_ok && standby_ok && resume_ok;

    std::cout << "\n========== WYNIK AUTOTESTU ==========" << '\n'
              << (normal_ok ? "[PASS]" : "[FAIL]")
              << " NORMAL generuje punkty (chmury=" << test.normal_clouds
              << ", punkty=" << test.normal_points << ")\n"
              << (standby_ok ? "[PASS]" : "[FAIL]")
              << " STANDBY zatrzymuje chmury i zostawia IMU"
              << " (chmury=" << test.standby_clouds
              << ", IMU=" << test.standby_imu << ")\n"
              << (resume_ok ? "[PASS]" : "[FAIL]")
              << " Powrot do NORMAL wznawia punkty"
              << " (chmury=" << test.resume_clouds
              << ", punkty=" << test.resume_points << ")\n"
              << "WYNIK CALKOWITY: " << (passed ? "PASS" : "FAIL / SPRAWDZ OSTRZEZENIA")
              << "\n=====================================\n\n";

    const bool exit_after = test.exit_after;
    test.phase = AutoTestPhase::Idle;
    return exit_after;
}

struct Arguments {
    std::string port = "/dev/ttyUSB0";
    std::uint32_t baudrate = 2000000U;
    float range_min = 0.05F;
    float range_max = 30.0F;
    std::uint16_t cloud_scan_num = 18;
    bool autotest = false;
};

void printUsage(const char* program) {
    std::cout
        << "Uzycie:\n  " << program
        << " [port] [baudrate] [range_min] [range_max] [cloud_scan_num] [--autotest]\n\n"
        << "Przyklad:\n  " << program << " /dev/ttyUSB0 2000000 0.05 30 18\n"
        << "  " << program << " /dev/ttyUSB0 --autotest\n";
}

bool parseArguments(int argc, char* argv[], Arguments& args) {
    int positional = 0;
    try {
        for (int i = 1; i < argc; ++i) {
            const std::string value = argv[i];
            if (value == "--autotest" || value == "-t") {
                args.autotest = true;
                continue;
            }
            if (value == "--help" || value == "-h") {
                printUsage(argv[0]);
                return false;
            }

            switch (positional++) {
                case 0: args.port = value; break;
                case 1: args.baudrate = static_cast<std::uint32_t>(std::stoul(value)); break;
                case 2: args.range_min = std::stof(value); break;
                case 3: args.range_max = std::stof(value); break;
                case 4: args.cloud_scan_num = static_cast<std::uint16_t>(std::stoul(value)); break;
                default:
                    std::cerr << "Za duzo argumentow.\n";
                    printUsage(argv[0]);
                    return false;
            }
        }
    } catch (const std::exception& error) {
        std::cerr << "Bledny argument: " << error.what() << '\n';
        printUsage(argv[0]);
        return false;
    }

    if (args.range_min < 0.0F || args.range_max <= args.range_min || args.cloud_scan_num == 0) {
        std::cerr << "Niepoprawny zakres albo cloud_scan_num.\n";
        return false;
    }
    return true;
}
} // namespace

int main(int argc, char* argv[]) {
    Arguments args;
    if (!parseArguments(argc, argv, args)) {
        return argc > 1 ? 1 : 0;
    }

    std::signal(SIGINT, handleSignal);
    std::signal(SIGTERM, handleSignal);

    std::cout << "Unitree 4D LiDAR L1 - tester Raspberry Pi\n"
              << "Port: " << args.port
              << " | baud: " << args.baudrate
              << " | zakres SDK: " << args.range_min << "-" << args.range_max << " m"
              << " | cloud_scan_num: " << args.cloud_scan_num << "\n";

    UnitreeLidarReader* reader = createUnitreeLidarReader();
    if (reader == nullptr) {
        std::cerr << "Nie udalo sie utworzyc obiektu oficjalnego SDK Unitree.\n";
        return 1;
    }

    const int init_result = reader->initialize(
        args.cloud_scan_num,
        args.port,
        args.baudrate,
        0.0F,      // rotate_yaw_bias
        0.001F,    // range_scale: mm -> m
        0.0F,      // range_bias
        args.range_max,
        args.range_min);

    if (init_result != 0) {
        std::cerr
            << "Nie udalo sie otworzyc portu " << args.port << ".\n"
            << "Sprawdz:\n"
            << "  ls -l /dev/serial/by-id/ 2>/dev/null\n"
            << "  ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null\n"
            << "  groups\n"
            << "oraz czy nikt inny nie zajmuje portu: sudo lsof " << args.port << "\n";
        return 2;
    }

    std::cout << "Port otwarty. Ustawiam tryb NORMAL.\n";
    reader->setLidarWorkingMode(NORMAL);
    reader->printConfig();

    Statistics stats;
    AutoTest auto_test;
    bool cycle_pending = false;
    Clock::time_point cycle_restart_at{};
    auto next_status = Clock::now() + std::chrono::seconds(1);

    if (args.autotest) {
        startAutoTest(reader, stats, auto_test, true);
    } else {
        printHelp();
    }

    while (keep_running) {
        const MessageType message = reader->runParse();

        switch (message) {
            case POINTCLOUD:
                updateCloudStats(reader->getCloud(), stats);
                break;
            case IMU:
                updateImuStats(reader->getIMU(), stats);
                break;
            case AUXILIARY:
                stats.auxiliary_total++;
                break;
            case VERSION:
                stats.version_total++;
                break;
            default:
                break;
        }

        const auto now = Clock::now();

        if (cycle_pending && now >= cycle_restart_at) {
            reader->setLidarWorkingMode(NORMAL);
            cycle_pending = false;
            std::cout << "[CYCLE] LiDAR ponownie w trybie NORMAL.\n";
        }

        if (updateAutoTest(reader, stats, auto_test)) {
            keep_running = false;
        }

        if (now >= next_status) {
            printStatus(stats);
            next_status = now + std::chrono::seconds(1);
        }

        if (!args.autotest && stdinReady()) {
            std::string line;
            if (!std::getline(std::cin, line)) {
                keep_running = false;
                break;
            }

            std::istringstream input(line);
            std::string command;
            input >> command;
            command = lowerCopy(command);

            if (command.empty()) {
                continue;
            } else if (command == "start" || command == "s") {
                cycle_pending = false;
                auto_test.phase = AutoTestPhase::Idle;
                reader->setLidarWorkingMode(NORMAL);
                std::cout << "Tryb NORMAL wyslany.\n";
            } else if (command == "stop" || command == "x") {
                cycle_pending = false;
                auto_test.phase = AutoTestPhase::Idle;
                reader->setLidarWorkingMode(STANDBY);
                std::cout << "Tryb STANDBY wyslany. Silniki i punkty powinny sie zatrzymac.\n";
            } else if (command == "cycle" || command == "c") {
                auto_test.phase = AutoTestPhase::Idle;
                reader->setLidarWorkingMode(STANDBY);
                cycle_pending = true;
                cycle_restart_at = Clock::now() + std::chrono::seconds(3);
                std::cout << "[CYCLE] STANDBY; powrot do NORMAL za 3 sekundy.\n";
            } else if (command == "autotest" || command == "t") {
                cycle_pending = false;
                startAutoTest(reader, stats, auto_test, false);
            } else if (command == "reset" || command == "r") {
                cycle_pending = false;
                auto_test.phase = AutoTestPhase::Idle;
                reader->reset();
                std::cout << "RESET wyslany. Poczekaj kilka sekund na ponowne dane.\n";
            } else if (command == "info" || command == "i") {
                printInfo(reader, stats);
            } else if (command == "status") {
                printStatus(stats, false);
            } else if (command == "points" || command == "p") {
                std::size_t count = 10;
                if (input >> count) {
                    count = std::min<std::size_t>(count, 100);
                }
                printPoints(stats, count);
            } else if (command == "imu") {
                printImu(stats);
            } else if (command == "snapshot") {
                std::string filename;
                if (!(input >> filename)) {
                    filename = defaultSnapshotName();
                }
                saveSnapshot(stats, filename);
            } else if (command == "led") {
                std::string mode;
                input >> mode;
                setLed(reader, lowerCopy(mode));
            } else if (command == "clear") {
                stats.clear();
                std::cout << "Statystyki wyzerowane.\n";
            } else if (command == "help" || command == "h") {
                printHelp();
            } else if (command == "quit" || command == "q") {
                keep_running = false;
            } else {
                std::cout << "Nieznana komenda. Wpisz help.\n";
            }
        }

        if (message == NONE) {
            std::this_thread::sleep_for(std::chrono::microseconds(200));
        }
    }

    std::cout << "Ustawiam STANDBY przed zakonczeniem...\n";
    reader->setLidarWorkingMode(STANDBY);
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    std::cout << "Podsumowanie: chmury=" << stats.clouds_total
              << ", punkty=" << stats.points_total
              << ", IMU=" << stats.imu_total << '\n';
    return 0;
}
