"""VideoPropertiesとスケーリング関連関数のテスト"""

import pytest

from media_scribe_workflow.ui.models import (
    VideoProperties,
    calculate_target_properties,
    build_scaling_filter,
)


class TestVideoProperties:
    """VideoPropertiesデータクラスのテスト"""

    def test_default_values(self):
        """デフォルト値が正しく設定される"""
        props = VideoProperties()
        assert props.width == 0
        assert props.height == 0
        assert props.sar_num == 1
        assert props.sar_den == 1
        assert props.dar_num == 16
        assert props.dar_den == 9
        assert props.fps_num == 30
        assert props.fps_den == 1
        assert props.is_interlaced is False
        assert props.field_order == "progressive"

    def test_display_width_square_pixels(self):
        """SAR 1:1（正方形ピクセル）の場合、display_width == width"""
        props = VideoProperties(width=1920, height=1080, sar_num=1, sar_den=1)
        assert props.display_width == 1920

    def test_display_width_anamorphic(self):
        """アナモルフィック（SAR 4:3）の場合、display_widthが補正される"""
        # 1440x1080 SAR 4:3 → display_width = 1440 * 4/3 = 1920
        props = VideoProperties(width=1440, height=1080, sar_num=4, sar_den=3)
        assert props.display_width == 1920

    def test_display_height_unchanged(self):
        """display_heightはheightと同じ"""
        props = VideoProperties(width=1920, height=1080)
        assert props.display_height == 1080

    def test_pixel_count_square_pixels(self):
        """正方形ピクセルのピクセル数"""
        props = VideoProperties(width=1920, height=1080, sar_num=1, sar_den=1)
        assert props.pixel_count == 1920 * 1080

    def test_pixel_count_anamorphic(self):
        """アナモルフィックのピクセル数は表示解像度ベース"""
        # 1440x1080 SAR 4:3 → display 1920x1080
        props = VideoProperties(width=1440, height=1080, sar_num=4, sar_den=3)
        assert props.pixel_count == 1920 * 1080

    def test_fps_calculation(self):
        """フレームレート計算"""
        # 30000/1001 ≈ 29.97 fps (NTSC)
        props = VideoProperties(fps_num=30000, fps_den=1001)
        assert abs(props.fps - 29.97) < 0.01

    def test_fps_simple(self):
        """シンプルなフレームレート"""
        props = VideoProperties(fps_num=25, fps_den=1)
        assert props.fps == 25.0

    def test_aspect_ratio(self):
        """アスペクト比計算"""
        props = VideoProperties(dar_num=16, dar_den=9)
        assert abs(props.aspect_ratio - 16/9) < 0.001


class TestCalculateTargetProperties:
    """calculate_target_propertiesのテスト"""

    def test_empty_list_returns_none(self):
        """空リストはNoneを返す"""
        result = calculate_target_properties([])
        assert result is None

    def test_single_source_progressive(self):
        """単一ソース（プログレッシブ）はそのまま"""
        source = VideoProperties(
            width=1920, height=1080, sar_num=1, sar_den=1,
            dar_num=16, dar_den=9, fps_num=30, fps_den=1,
            is_interlaced=False
        )
        result = calculate_target_properties([source])

        assert result.width == 1920
        assert result.height == 1080
        assert result.sar_num == 1
        assert result.sar_den == 1
        assert result.is_interlaced is False

    def test_single_source_interlaced_becomes_progressive(self):
        """単一ソース（インターレース）はプログレッシブになる"""
        source = VideoProperties(
            width=1920, height=1080, sar_num=1, sar_den=1,
            is_interlaced=True, field_order="tt"
        )
        result = calculate_target_properties([source])

        assert result.is_interlaced is False
        assert result.field_order == "progressive"

    def test_single_source_anamorphic_to_square_pixels(self):
        """アナモルフィックソースはdisplay_widthが使用される"""
        source = VideoProperties(
            width=1440, height=1080, sar_num=4, sar_den=3,
            dar_num=16, dar_den=9
        )
        result = calculate_target_properties([source])

        # SAR 4:3 の 1440x1080 → 1920x1080
        assert result.width == 1920
        assert result.height == 1080
        assert result.sar_num == 1
        assert result.sar_den == 1

    def test_multiple_sources_uses_min_pixel_count(self):
        """複数ソースは最小ピクセル数を使用"""
        source_hd = VideoProperties(width=1920, height=1080, sar_num=1, sar_den=1)  # 2,073,600 pixels
        source_720p = VideoProperties(width=1280, height=720, sar_num=1, sar_den=1)  # 921,600 pixels

        result = calculate_target_properties([source_hd, source_720p])

        assert result.width == 1280
        assert result.height == 720

    def test_multiple_sources_uses_min_fps(self):
        """複数ソースは最小fpsを使用"""
        source_30fps = VideoProperties(
            width=1920, height=1080, sar_num=1, sar_den=1,
            fps_num=30, fps_den=1
        )
        source_24fps = VideoProperties(
            width=1920, height=1080, sar_num=1, sar_den=1,
            fps_num=24, fps_den=1
        )

        result = calculate_target_properties([source_30fps, source_24fps])

        assert result.fps_num == 24
        assert result.fps_den == 1

    def test_multiple_sources_always_progressive(self):
        """複数ソース結合時は常にプログレッシブ"""
        source_interlaced = VideoProperties(
            width=1920, height=1080, is_interlaced=True
        )
        source_progressive = VideoProperties(
            width=1920, height=1080, is_interlaced=False
        )

        result = calculate_target_properties([source_interlaced, source_progressive])

        assert result.is_interlaced is False


class TestBuildScalingFilter:
    """build_scaling_filterのテスト"""

    def test_same_properties_still_scales(self):
        """同じプロパティでもスケーリングフィルタは生成される"""
        source = VideoProperties(
            width=1920, height=1080, sar_num=1, sar_den=1,
            fps_num=30, fps_den=1, is_interlaced=False
        )
        target = VideoProperties(
            width=1920, height=1080, sar_num=1, sar_den=1,
            fps_num=30, fps_den=1, is_interlaced=False
        )

        result = build_scaling_filter(source, target)

        # scale, pad は必ず含まれる
        assert "scale=" in result
        assert "pad=" in result
        # 同じfpsなのでfpsフィルタは含まれない
        assert "fps=" not in result

    def test_interlaced_source_adds_yadif(self):
        """インターレースソースにはyadifが追加される"""
        source = VideoProperties(
            width=1920, height=1080, is_interlaced=True
        )
        target = VideoProperties(
            width=1920, height=1080, is_interlaced=False
        )

        result = build_scaling_filter(source, target)

        assert "yadif=mode=1" in result

    def test_progressive_source_no_yadif(self):
        """プログレッシブソースにはyadifが追加されない"""
        source = VideoProperties(
            width=1920, height=1080, is_interlaced=False
        )
        target = VideoProperties(
            width=1920, height=1080, is_interlaced=False
        )

        result = build_scaling_filter(source, target)

        assert "yadif" not in result

    def test_different_resolution_scales(self):
        """異なる解像度はスケーリングされる"""
        source = VideoProperties(width=1920, height=1080)
        target = VideoProperties(width=1280, height=720)

        result = build_scaling_filter(source, target)

        assert "scale=1280:720" in result
        assert "pad=1280:720:" in result

    def test_different_fps_converts(self):
        """異なるfpsはfpsフィルタで変換される"""
        source = VideoProperties(fps_num=30, fps_den=1)
        target = VideoProperties(fps_num=24, fps_den=1)

        result = build_scaling_filter(source, target)

        assert "fps=24/1" in result

    def test_same_fps_no_convert(self):
        """同じfpsはfpsフィルタなし"""
        source = VideoProperties(fps_num=30, fps_den=1)
        target = VideoProperties(fps_num=30, fps_den=1)

        result = build_scaling_filter(source, target)

        assert "fps=" not in result

    def test_filter_order(self):
        """フィルタの順序: yadif → scale → pad → fps"""
        source = VideoProperties(
            width=1920, height=1080, is_interlaced=True,
            fps_num=30, fps_den=1
        )
        target = VideoProperties(
            width=1280, height=720, is_interlaced=False,
            fps_num=24, fps_den=1
        )

        result = build_scaling_filter(source, target)

        # フィルタの順序を確認
        yadif_pos = result.find("yadif")
        scale_pos = result.find("scale=")
        pad_pos = result.find("pad=")
        fps_pos = result.find("fps=")

        assert yadif_pos < scale_pos
        assert scale_pos < pad_pos
        assert pad_pos < fps_pos

    def test_force_original_aspect_ratio(self):
        """アスペクト比維持オプションが含まれる"""
        source = VideoProperties(width=1920, height=1080)
        target = VideoProperties(width=1280, height=720)

        result = build_scaling_filter(source, target)

        assert "force_original_aspect_ratio=decrease" in result

    def test_padding_centered(self):
        """パディングが中央配置される"""
        source = VideoProperties(width=1920, height=1080)
        target = VideoProperties(width=1280, height=720)

        result = build_scaling_filter(source, target)

        # (ow-iw)/2:(oh-ih)/2 で中央配置（blackはffmpegのデフォルト）
        assert "(ow-iw)/2:(oh-ih)/2" in result
