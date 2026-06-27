from __future__ import annotations


def explain_capacity(metric: str, server_ip: str, hours: float, current: float, severity: str) -> str:
    days = hours / 24
    if days < 1:
        time_str = f"{hours:.0f} giờ"
    else:
        time_str = f"{days:.1f} ngày"
    label = {"cpu_pct": "CPU", "ram_pct": "RAM", "disk_pct": "Disk"}.get(metric, metric)
    return (
        f"[Dự báo] Server {server_ip}: {label} hiện tại {current:.1f}%, "
        f"dự kiến đạt ngưỡng 95% trong ~{time_str}. "
        f"Mức độ: {severity.upper()}."
    )


def explain_baseline_deviation(
    metric: str, server_ip: str | None, current: float, mean: float, z: float
) -> str:
    label = {"cpu_pct": "CPU", "ram_pct": "RAM", "disk_pct": "Disk", "error_count": "Số lỗi"}.get(metric, metric)
    host = f"server {server_ip}" if server_ip else "hệ thống"
    return (
        f"[Bất thường] {host}: {label} = {current:.1f} "
        f"(baseline trung bình {mean:.1f}, z-score = {z:.1f}σ). "
        f"Vượt ngưỡng bình thường đáng kể."
    )


def explain_acceleration(metric: str, server_ip: str, slope: float) -> str:
    label = {"cpu_pct": "CPU", "ram_pct": "RAM", "disk_pct": "Disk"}.get(metric, metric)
    return (
        f"[Tăng tốc] Server {server_ip}: {label} đang tăng "
        f"{slope * 100:.1f}%/giờ — tốc độ tăng bất thường."
    )


def explain_novelty(pattern: str, similarity: float) -> str:
    return (
        f"[Lỗi mới] Xuất hiện pattern lỗi chưa từng gặp trước đây "
        f"(similarity với pattern đã biết = {similarity:.0%}): {pattern[:100]}..."
    )


def explain_recurrence(title: str, similarity: float, solution: str | None) -> str:
    msg = f"[Tái phát] Sự cố tương tự '{title}' đã xảy ra trước đây (similarity {similarity:.0%})."
    if solution:
        msg += f" Giải pháp đề xuất: {solution[:200]}"
    return msg


def explain_composite(groups: list[str]) -> str:
    return (
        f"[Tổng hợp] Phát hiện {len(groups)} loại tín hiệu bất thường đồng thời: "
        f"{', '.join(groups)}. Khả năng sự cố cao."
    )
