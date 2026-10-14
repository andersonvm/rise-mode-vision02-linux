"""Testes do gerenciador de perfis sem hardware."""

import threading

import pytest

from vision02.profiles import (
    Profile,
    ProfileManager,
    ProfileManagerError,
)


@pytest.fixture
def manager():
    return ProfileManager()


def make_profile(name):
    return Profile(name=name)


def write_profile(tmp_path, filename, name, version=1):
    path = tmp_path / filename
    path.write_text(
        f"version: {version}\n"
        f"name: {name}\n"
        "keys: {}\n",
        encoding="utf-8",
    )
    return path


def test_manager_starts_without_active_profile(manager):
    assert manager.active_name is None
    assert manager.list_profiles() == ()


def test_active_without_profiles_raises(manager):
    with pytest.raises(ProfileManagerError, match="Nenhum perfil"):
        manager.active


def test_first_registered_profile_becomes_active(manager):
    profile = make_profile("Desenvolvimento")

    manager.register(profile)

    assert manager.active is profile
    assert manager.active_name == "Desenvolvimento"


def test_switch_between_profiles(manager):
    development = make_profile("Desenvolvimento")
    observability = make_profile("Observabilidade")

    manager.register(development)
    manager.register(observability)

    selected = manager.switch("Observabilidade")

    assert selected is observability
    assert manager.active is observability


def test_unknown_profile_does_not_change_active(manager):
    manager.register(make_profile("Desenvolvimento"))

    with pytest.raises(ProfileManagerError, match="não encontrado"):
        manager.switch("Inexistente")

    assert manager.active_name == "Desenvolvimento"


def test_duplicate_profile_is_rejected(manager):
    manager.register(make_profile("Desenvolvimento"))

    with pytest.raises(ProfileManagerError, match="já registrado"):
        manager.register(make_profile("Desenvolvimento"))


def test_empty_profile_name_rejected(manager):
    with pytest.raises(ProfileManagerError, match="vazio"):
        manager.register(make_profile("   "))


def test_list_profiles(manager):
    manager.register(make_profile("Desenvolvimento"))
    manager.register(make_profile("Observabilidade"))

    assert manager.list_profiles() == (
        "Desenvolvimento",
        "Observabilidade",
    )


def test_get_does_not_switch_profile(manager):
    manager.register(make_profile("Desenvolvimento"))
    second = make_profile("Observabilidade")
    manager.register(second)

    assert manager.get("Observabilidade") is second
    assert manager.active_name == "Desenvolvimento"


def test_load_valid_yaml(manager, tmp_path):
    path = write_profile(
        tmp_path,
        "desenvolvimento.yaml",
        "Desenvolvimento",
    )

    profile = manager.load(path)

    assert profile.name == "Desenvolvimento"
    assert manager.active is profile


def test_load_many_registers_all_profiles(manager, tmp_path):
    first = write_profile(
        tmp_path,
        "desenvolvimento.yaml",
        "Desenvolvimento",
    )
    second = write_profile(
        tmp_path,
        "observabilidade.yaml",
        "Observabilidade",
    )

    profiles = manager.load_many([first, second])

    assert len(profiles) == 2
    assert manager.list_profiles() == (
        "Desenvolvimento",
        "Observabilidade",
    )


def test_invalid_batch_does_not_register_profiles(manager, tmp_path):
    first = write_profile(
        tmp_path,
        "valido.yaml",
        "Desenvolvimento",
    )
    invalid = write_profile(
        tmp_path,
        "invalido.yaml",
        "Observabilidade",
        version=99,
    )

    with pytest.raises(ValueError):
        manager.load_many([first, invalid])

    assert manager.list_profiles() == ()
    assert manager.active_name is None


def test_duplicate_names_in_batch_rejected(manager, tmp_path):
    first = write_profile(
        tmp_path,
        "primeiro.yaml",
        "Duplicado",
    )
    second = write_profile(
        tmp_path,
        "segundo.yaml",
        "Duplicado",
    )

    with pytest.raises(ProfileManagerError, match="duplicados"):
        manager.load_many([first, second])

    assert manager.list_profiles() == ()


def test_concurrent_switches_preserve_valid_state(manager):
    manager.register(make_profile("Desenvolvimento"))
    manager.register(make_profile("Observabilidade"))

    errors = []

    def switch_repeatedly(name):
        try:
            for _ in range(100):
                manager.switch(name)
                assert manager.active_name in {
                    "Desenvolvimento",
                    "Observabilidade",
                }
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(
            target=switch_repeatedly,
            args=(name,),
        )
        for name in ("Desenvolvimento", "Observabilidade")
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=3)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert manager.active_name in {
        "Desenvolvimento",
        "Observabilidade",
    }
