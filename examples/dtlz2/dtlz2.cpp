// DTLZ2 with 3 objectives (all minimized) and 12 variables: the C++ example of paretolab.
//
// build:  g++ -O2 -std=c++17 dtlz2.cpp -o dtlz2
// usage:  dtlz2 <variant> <seed> <max evaluations> <result file> [--name=value ...]
//
// variants: paes (a (1+1) evolution strategy with a bounded Pareto archive, after Knowles and Corne) or random;
// parameters (paes only): --sigma (mutation step) and --archive_size.
// The true Pareto front is the part of the unit sphere with every objective >= 0.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <map>
#include <random>
#include <string>
#include <vector>

using Vec = std::vector<double>;
const int M = 3, N = M + 9;   // k = 10 distance variables
const double PI = 3.14159265358979323846;

Vec dtlz2(const Vec& x) {
    double g = 0;
    for (int i = M - 1; i < N; ++i) g += (x[i] - 0.5) * (x[i] - 0.5);
    Vec f(M, 1.0 + g);
    for (int m = 0; m < M; ++m) {
        for (int j = 0; j < M - 1 - m; ++j) f[m] *= std::cos(x[j] * PI / 2);
        if (m > 0) f[m] *= std::sin(x[M - 1 - m] * PI / 2);
    }
    return f;
}

bool dominates(const Vec& a, const Vec& b) {
    bool better = false;
    for (int m = 0; m < M; ++m) {
        if (a[m] > b[m]) return false;
        if (a[m] < b[m]) better = true;
    }
    return better;
}

struct Point { Vec x, f; };

// Adds p to the archive unless it is dominated or repeated; drops what it dominates; returns whether it entered.
bool add(std::vector<Point>& archive, const Point& p, size_t limit) {
    for (const auto& a : archive)
        if (dominates(a.f, p.f) || a.f == p.f) return false;
    archive.erase(std::remove_if(archive.begin(), archive.end(),
                                 [&](const Point& a) { return dominates(p.f, a.f); }), archive.end());
    archive.push_back(p);
    while (archive.size() > limit) {   // drop the point closest to its nearest neighbour (most crowded)
        size_t worst = 0;
        double worst_d = std::numeric_limits<double>::infinity();
        for (size_t i = 0; i < archive.size(); ++i) {
            double nearest = std::numeric_limits<double>::infinity();
            for (size_t j = 0; j < archive.size(); ++j) {
                if (i == j) continue;
                double d = 0;
                for (int m = 0; m < M; ++m) d += std::pow(archive[i].f[m] - archive[j].f[m], 2);
                nearest = std::min(nearest, d);
            }
            if (nearest < worst_d) { worst_d = nearest; worst = i; }
        }
        archive.erase(archive.begin() + worst);
    }
    return std::find_if(archive.begin(), archive.end(), [&](const Point& a) { return a.f == p.f; }) != archive.end();
}

int main(int argc, char** argv) {
    if (argc < 5) {
        std::fprintf(stderr, "usage: dtlz2 <variant> <seed> <max evaluations> <result file> [--name=value ...]\n");
        return 2;
    }
    auto start = std::chrono::steady_clock::now();
    std::string variant = argv[1];
    std::mt19937_64 rng(std::strtoull(argv[2], nullptr, 10));
    long budget = std::atol(argv[3]);
    std::map<std::string, std::string> params;
    for (int i = 5; i < argc; ++i) {
        std::string a = argv[i];
        auto eq = a.find('=');
        if (a.rfind("--", 0) == 0 && eq != std::string::npos) params[a.substr(2, eq - 2)] = a.substr(eq + 1);
    }
    double sigma = params.count("sigma") ? std::atof(params["sigma"].c_str()) : 0.1;
    size_t limit = params.count("archive_size") ? std::atol(params["archive_size"].c_str()) : 100;
    if (variant == "random") limit = std::numeric_limits<size_t>::max();

    std::uniform_real_distribution<double> unit(0.0, 1.0);
    std::normal_distribution<double> gauss(0.0, 1.0);
    auto random_point = [&]() { Point p; p.x.resize(N); for (auto& v : p.x) v = unit(rng); p.f = dtlz2(p.x); return p; };

    std::vector<Point> archive;
    long evaluations = 0;
    Point current = random_point();
    ++evaluations;
    add(archive, current, limit);
    while (evaluations < budget) {
        Point child;
        if (variant == "random") {
            child = random_point();
        } else {
            child.x = current.x;
            for (auto& v : child.x)
                if (unit(rng) < 2.0 / N) v = std::clamp(v + sigma * gauss(rng), 0.0, 1.0);
            child.f = dtlz2(child.x);
        }
        ++evaluations;
        bool entered = add(archive, child, limit);
        if (variant == "paes") {
            if (dominates(child.f, current.f) || (entered && !dominates(current.f, child.f) && unit(rng) < 0.5))
                current = child;
            if (unit(rng) < 0.01) current = archive[rng() % archive.size()];   // occasional restart from the archive
        }
    }

    double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    FILE* out = std::fopen(argv[4], "w");
    if (!out) { std::perror(argv[4]); return 1; }
    std::fprintf(out, "{\"front\": [");
    for (size_t i = 0; i < archive.size(); ++i)
        std::fprintf(out, "%s[%.17g, %.17g, %.17g]", i ? ", " : "", archive[i].f[0], archive[i].f[1], archive[i].f[2]);
    std::fprintf(out, "], \"evaluations\": %ld, \"wall_time_s\": %.4f}\n", evaluations, seconds);
    std::fclose(out);
    return 0;
}
