import subprocess
from pathlib import Path

import pytest

from spotify_autoeq.apps.autoeq import cli, doctor, systemd_unit
from spotify_autoeq.apps.autoeq.config import default_config_path


class Recorder:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, argv):
        self.calls.append(list(argv))
        code = 1 if self.fail_on and self.fail_on in argv else 0
        return subprocess.CompletedProcess(argv, code, "", "boom" if code else "")


def test_exec_start_quotes_unusual_paths():
    assert systemd_unit.exec_start("/usr/bin/python3").startswith("/usr/bin/python3 -m ")
    quoted = systemd_unit.exec_start("/home/a b/venv/bin/python")
    assert quoted.startswith('"/home/a b/venv/bin/python" -m ')
    assert systemd_unit.exec_start("/x/100%/py").startswith('"/x/100%%/py"')


def test_render_unit_has_no_placeholder_and_is_valid_shape():
    text = systemd_unit.render_unit("/opt/venv/bin/python")
    assert "@EXEC_START@" not in text
    assert "ExecStart=/opt/venv/bin/python -m spotify_autoeq.apps.autoeq run" in text
    assert "Restart=on-failure" in text and "WantedBy=graphical-session.target" in text


def test_install_and_uninstall_with_fake_systemctl(tmp_path):
    rec = Recorder()
    path = systemd_unit.install(unit_dir=tmp_path, python="/p/python", runner=rec)
    assert path == tmp_path / "spotify-autoeq.service" and path.exists()
    assert [c[2] for c in rec.calls] == ["daemon-reload", "enable", "restart"]
    rec2 = Recorder()
    assert systemd_unit.uninstall(unit_dir=tmp_path, runner=rec2) is True
    assert not path.exists()
    assert systemd_unit.uninstall(unit_dir=tmp_path, runner=Recorder()) is False


def test_install_reports_systemctl_failure(tmp_path):
    with pytest.raises(systemd_unit.ServiceError, match="enable"):
        systemd_unit.install(unit_dir=tmp_path, python="/p", runner=Recorder(fail_on="enable"))


def test_install_without_systemctl_only_writes_file(tmp_path):
    rec = Recorder()
    systemd_unit.install(unit_dir=tmp_path, python="/p", runner=rec, use_systemctl=False)
    assert rec.calls == [] and (tmp_path / "spotify-autoeq.service").exists()


def fake_runner(server="pulseaudio", players="spotify\n"):
    def run(argv):
        if argv[:2] == ["pactl", "info"]:
            return subprocess.CompletedProcess(argv, 0, f"Server Name: {server}\n", "")
        if argv[:2] == ["playerctl", "-l"]:
            return subprocess.CompletedProcess(argv, 0, players, "")
        return subprocess.CompletedProcess(argv, 1, "", "")
    return run


def checks(tmp_path, *, which=lambda b: f"/usr/bin/{b}", schema=True, server="pulseaudio",
           lv2=True, **kw):
    lv2_dir = tmp_path / "lv2"
    cfg = tmp_path / "ok.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("player: spotify\n")
    if lv2:
        (lv2_dir / "lsp-plugins.lv2").mkdir(parents=True)
    return {c.name: c for c in doctor.run_checks(
        cfg, runner=fake_runner(server), which=which,
        schema_probe=lambda: schema, lv2_dirs=[str(lv2_dir)], **kw)}


def test_doctor_all_good(tmp_path):
    result = checks(tmp_path)
    assert doctor.all_required_ok(list(result.values()))
    assert result["sound server"].detail == "pulseaudio"


def test_doctor_flags_pipewire_and_missing_pieces(tmp_path):
    result = checks(tmp_path, server="PulseAudio (on PipeWire 0.3.48)")
    assert not result["sound server"].ok and "PipeWire" in result["sound server"].hint
    missing = checks(tmp_path / "x", which=lambda b: None, schema=None, lv2=False)
    assert not missing["playerctl"].ok and not missing["pulseeffects"].ok
    assert not missing["PyGObject (gi)"].ok and not missing["LSP equalizer plugins"].ok
    assert not doctor.all_required_ok(list(missing.values()))
    assert "FAIL" in doctor.format_report(list(missing.values()))


def test_doctor_spotify_is_informational(tmp_path):
    def run(argv):
        return fake_runner(players="")(argv)

    ok_cfg = tmp_path / "ok.yaml"
    ok_cfg.write_text("player: spotify\n")
    result = {c.name: c for c in doctor.run_checks(
        ok_cfg, runner=run, which=lambda b: "/x", schema_probe=lambda: True,
        lv2_dirs=[str(tmp_path)])}
    assert not result["Spotify"].ok and not result["Spotify"].required
    assert "warn" in doctor.format_report([result["Spotify"]])


def test_doctor_reports_invalid_config(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("bogus: 1\n")
    result = {c.name: c for c in doctor.run_checks(
        bad, runner=fake_runner(), which=lambda b: "/x", schema_probe=lambda: True,
        lv2_dirs=[str(tmp_path)])}
    assert not result["configuration"].ok


def test_config_init_and_path(tmp_path, capsys):
    target = tmp_path / "sub" / "c.yaml"
    assert cli.main(["-c", str(target), "config", "init"]) == 0
    assert target.exists() and "resolver:" in target.read_text()
    assert cli.main(["-c", str(target), "config", "init"]) == 1
    target.write_text("player: x\n")
    assert cli.main(["-c", str(target), "config", "init", "--force"]) == 0
    assert "resolver:" in target.read_text()
    capsys.readouterr()
    assert cli.main(["-c", str(target), "config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(target)


def test_config_path_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(default_config_path())


def test_service_cli_without_systemctl(tmp_path, capsys):
    assert cli.main(["service", "install", "--unit-dir", str(tmp_path), "--no-systemctl"]) == 0
    assert (tmp_path / "spotify-autoeq.service").exists()
    assert cli.main(["service", "uninstall", "--unit-dir", str(tmp_path), "--no-systemctl"]) == 0
    assert "service removed" in capsys.readouterr().out
    assert cli.main(["service", "uninstall", "--unit-dir", str(tmp_path), "--no-systemctl"]) == 0
    assert "not installed" in capsys.readouterr().out
