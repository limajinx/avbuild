#include <stdio.h>
#include <libavcodec/avcodec.h>

int main(void) {
    void *cursor = NULL;
    const AVCodec *codec;
    while ((codec = av_codec_iterate(&cursor))) {
        if (av_codec_is_decoder(codec))
            printf("%s\t%s\n", codec->name, av_get_media_type_string(codec->type));
    }
    return 0;
}
