// Headless MDK prepare/seek smoke test. No rendering or audio-output claims.
#include <mdk/Player.h>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <thread>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    for (int cycle = 0; cycle < 3; cycle++) {
        std::atomic<int> prepared{0};
        std::atomic<int> frames{0};
        mdk::Player player;
        player.setDecoders(mdk::MediaType::Video, {"FFmpeg"});
        player.setMedia(argv[1]);
        player.setActiveTracks(mdk::MediaType::Subtitle, {});
        player.setActiveTracks(mdk::MediaType::Audio, {});
        player.onFrame<mdk::VideoFrame>([&](mdk::VideoFrame &frame, int) {
            if (frame.isValid()) frames++;
            return 0;
        });
        player.prepare(cycle ? 1000 : 0, [&](int64_t position, bool *) {
            prepared = position >= 0 ? 1 : -1;
            return true;
        });
        for (int i = 0; i < 100 && !prepared; i++)
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        if (prepared == 1) {
            player.set(mdk::State::Playing);
            for (int i = 0; i < 100 && frames == 0; i++)
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        const bool success = prepared == 1 && frames > 0;
        player.set(mdk::State::Stopped);
        if (!player.waitFor(mdk::State::Stopped, 5000)) return 3;
        if (!success) {
            std::fprintf(stderr, "MDK prepare failed: prepared=%d frames=%d\n", prepared.load(), frames.load());
            return 1;
        }
        std::printf("PASS MDK software prepare cycle=%d frames=%d\n", cycle, frames.load());
    }
    return 0;
}
