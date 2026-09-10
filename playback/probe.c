/* Run on Android against the candidate library, never inside the production app. */
#include <stdio.h>
#include <dlfcn.h>
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>

static int decode_sample(const char *url, const char *ca_file) {
    AVFormatContext *format = NULL;
    AVCodecContext *contexts[2] = {NULL, NULL};
    int streams[2], counts[2] = {0, 0};
    AVPacket *packet = av_packet_alloc();
    AVFrame *frame = av_frame_alloc();
    AVDictionary *options = NULL;
    int result = 1;
    if (ca_file) {
        av_dict_set(&options, "ca_file", ca_file, 0);
        av_dict_set(&options, "tls_verify", "1", 0);
    }
    if (avformat_open_input(&format, url, NULL, &options) < 0 ||
        avformat_find_stream_info(format, NULL) < 0) goto done;
    for (int i = 0; i < 2; i++) {
        const AVCodec *decoder = NULL;
        streams[i] = av_find_best_stream(format, i ? AVMEDIA_TYPE_AUDIO : AVMEDIA_TYPE_VIDEO,
                                         -1, -1, &decoder, 0);
        if (streams[i] < 0) goto done;
        printf("input %s decoder %s\n", i ? "audio" : "video", decoder->name);
        contexts[i] = avcodec_alloc_context3(decoder);
        if (!contexts[i] || avcodec_parameters_to_context(contexts[i], format->streams[streams[i]]->codecpar) < 0 ||
            avcodec_open2(contexts[i], decoder, NULL) < 0) goto done;
    }
    for (int pass = 0; pass < 2; pass++) {
        counts[0] = counts[1] = 0;
        while ((counts[0] < 10 || counts[1] < 10) && av_read_frame(format, packet) >= 0) {
            for (int i = 0; i < 2; i++) {
                if (packet->stream_index != streams[i]) continue;
                if (avcodec_send_packet(contexts[i], packet) < 0) goto done;
                int status;
                while ((status = avcodec_receive_frame(contexts[i], frame)) >= 0) {
                    counts[i]++;
                    av_frame_unref(frame);
                }
                if (status != AVERROR(EAGAIN) && status != AVERROR_EOF) goto done;
            }
            av_packet_unref(packet);
        }
        if (counts[0] < 10 || counts[1] < 10) goto done;
        printf("PASS software decode pass=%d video=%d audio=%d\n", pass, counts[0], counts[1]);
        if (!pass) {
            if (av_seek_frame(format, -1, AV_TIME_BASE, AVSEEK_FLAG_BACKWARD) < 0) goto done;
            for (int i = 0; i < 2; i++) avcodec_flush_buffers(contexts[i]);
        }
    }
    result = 0;
done:
    av_dict_free(&options);
    for (int i = 0; i < 2; i++) avcodec_free_context(&contexts[i]);
    avformat_close_input(&format);
    av_packet_free(&packet);
    av_frame_free(&frame);
    return result;
}

int main(int argc, char **argv) {
    void *cursor = NULL;
    const AVCodec *codec;
    int decoders = 0;
    while ((codec = av_codec_iterate(&cursor))) {
        if (av_codec_is_encoder(codec) || codec->type == AVMEDIA_TYPE_SUBTITLE) {
            fprintf(stderr, "Forbidden codec: %s\n", codec->name);
            return 1;
        }
        printf("decoder %s\n", codec->name);
        decoders++;
    }
    cursor = NULL;
    if (av_muxer_iterate(&cursor)) return 2;
    if (!avcodec_find_decoder_by_name("libdav1d")) return 3;
    printf("PASS %d decoders; no encoders, subtitle codecs or muxers\n", decoders);
    if (argc > 1) {
        void *mdk = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
        if (!mdk) {
            fprintf(stderr, "MDK load failed: %s\n", dlerror());
            return 4;
        }
        puts("PASS MDK ELF load (not playback validation)");
        dlclose(mdk);
    }
    if (argc > 2) {
        for (int i = 0; i < 3; i++) {
            if (decode_sample(argv[2], argc > 3 ? argv[3] : NULL)) return 5;
        }
        puts("PASS three decode/seek/dispose cycles (not rendered playback)");
    }
    return 0;
}
