import pytest


@pytest.fixture
def page(qapp):
    from gpuviewer_client.ui.overview_page import OverviewPage
    return OverviewPage(disk_warn_pct=90.0)   # 注入阈值，不读真实设置


def test_overview_cards(page, client_payload):
    clicked = []
    page.server_clicked.connect(clicked.append)
    page.update_snapshot(client_payload["servers"])
    assert page.card_names() == ["L40"]
    card = page._cards["l40"]
    assert card.cpu_kv.value.text() == "12%"          # 摘要行 CPU
    assert card.mem_kv.value.text() == "12G"          # used=13272248320B≈12.4G→12G
    assert card.meta_label.text().startswith("Ubuntu 22.04.4 LTS · 2 核")
    assert len(card.gpu_chips) == 1                   # GPU 迷你块
    chip = card.gpu_chips[0]
    assert chip.util_label.text() == "87%"
    assert chip.mem_label.text() == "33.2/45.0G"      # 34000/46068 MiB


def test_overview_offline_gray(page, client_payload):
    p = client_payload
    p["servers"][0]["status"] = "offline"
    page.update_snapshot(p["servers"])
    assert page._cards["l40"].dot._color.name() == "#6e7681"


def test_card_click(page, client_payload):
    clicked = []
    page.server_clicked.connect(clicked.append)
    page.update_snapshot(client_payload["servers"])
    page._cards["l40"].click()
    assert clicked == ["l40"]


def test_disk_over_threshold_red(qapp, client_payload):
    from gpuviewer_client.ui.overview_page import OverviewPage
    p50 = OverviewPage(disk_warn_pct=50.0)
    p50.update_snapshot(client_payload["servers"])
    assert "#f85149" in p50._cards["l40"].disk_label.styleSheet()   # error 色
    p90 = OverviewPage(disk_warn_pct=90.0)
    p90.update_snapshot(client_payload["servers"])
    assert "#9aa4b2" in p90._cards["l40"].disk_label.styleSheet()   # sub 色


def test_overview_recycles_vanished_cards(page, client_payload):
    """daemon 侧删除服务器后，总览幽灵卡片必须回收（与侧栏同步同一缺陷类）。"""
    page.update_snapshot(client_payload["servers"])
    assert page.card_names() == ["L40"]
    page.update_snapshot([])
    assert page.card_names() == []
    assert "l40" not in page._cards
