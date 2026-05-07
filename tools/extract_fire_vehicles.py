from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import pprint
from typing import Iterable

from beamngpy import BeamNGpy

root_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(root_dir))

import const
from run.beamng_home import BeamNGHomeNotFound, resolve_beamng_home


DEFAULT_KEYWORDS = (
    "fire",
    "firechief",
    "fire chief",
    "fire dept",
    "fire department",
    "firefighter",
    "rescue",
    "ladder",
    "engine",
)


@dataclass(frozen=True)
class FireVehicleEntry:
    display_name: str
    model: str
    part_config: str


class FireVehicleExtractor:
    def __init__(self, keywords: Iterable[str] = DEFAULT_KEYWORDS, license_tag: str = "EV") -> None:
        self.keywords = tuple(k.lower() for k in keywords)
        self.license_tag = license_tag

    def extract(self, available) -> list[FireVehicleEntry]:
        entries: list[FireVehicleEntry] = []
        seen = set()
        for model_key, model_info in self._iter_models(available):
            model_name = (model_info.get("name") or model_key or "").strip()
            if str(model_info.get("type", "")).lower() == "prop":
                continue
            configs = self._normalize_configs(
                model_info.get("configs") or model_info.get("configurations") or []
            )
            if not configs:
                continue
            for cfg in configs:
                config_name = (cfg.get("name") or cfg.get("key") or "").strip()
                config_path = (
                    cfg.get("path")
                    or cfg.get("config")
                    or cfg.get("file")
                    or cfg.get("pc")
                    or cfg.get("partConfig")
                    or ""
                ).strip()
                if not config_path:
                    config_path = self._build_part_config_path(model_key, cfg)
                if not config_path:
                    continue
                display_name = self._compose_display_name(model_name, config_name)
                if not self._matches_keywords(display_name, model_key, config_path):
                    continue
                entry_key = (model_key, config_path)
                if entry_key in seen:
                    continue
                seen.add(entry_key)
                entries.append(
                    FireVehicleEntry(
                        display_name=display_name,
                        model=model_key,
                        part_config=config_path,
                    )
                )
        return entries

    def format_entries(self, entries: Iterable[FireVehicleEntry]) -> str:
        lines = ["FIRE = ["]
        for entry in entries:
            lines.append(
                "    Vehicle(\"(Vehicle) {name}\", model=\"{model}\", part_config=\"{config}\", licence=\"{licence}\"),".format(
                    name=entry.display_name,
                    model=entry.model,
                    config=entry.part_config,
                    licence=self.license_tag,
                )
            )
        lines.append("]")
        return "\n".join(lines)

    def _normalize_configs(self, configs) -> list[dict]:
        if isinstance(configs, dict):
            configs = list(configs.values())
        if not isinstance(configs, list):
            return []
        return [cfg for cfg in configs if isinstance(cfg, dict)]

    def _matches_keywords(self, *values: str) -> bool:
        haystack = " ".join(value.lower() for value in values if value)
        return any(keyword in haystack for keyword in self.keywords)

    def _compose_display_name(self, model_name: str, config_name: str) -> str:
        if not model_name:
            return config_name
        if config_name and config_name.lower() not in model_name.lower():
            return f"{model_name} {config_name}".strip()
        return model_name

    def _build_part_config_path(self, model_key: str, cfg: dict) -> str:
        config_key = (cfg.get("key") or cfg.get("config") or "").strip()
        if not model_key or not config_key:
            return ""
        return f"vehicles/{model_key}/{config_key}.pc"

    def _iter_models(self, available):
        if isinstance(available, dict):
            for model_key, model_info in available.items():
                if isinstance(model_info, dict):
                    yield str(model_key), model_info
            return
        if isinstance(available, list):
            for item in available:
                if isinstance(item, dict):
                    model_key = item.get("model") or item.get("key") or item.get("id") or ""
                    yield str(model_key), item


def main() -> None:
    try:
        beamng_home = resolve_beamng_home(getattr(const, "BEAMNG_LOCATION", None))
    except BeamNGHomeNotFound as exc:
        raise RuntimeError(str(exc)) from exc

    bng = BeamNGpy(host="localhost", port=25252, home=beamng_home)
    bng.open(launch=True)
    try:
        available = bng.vehicles.get_available()
    finally:
        bng.close()

    output_path = Path(__file__).resolve().parent / "fire_vehicles.txt"
    raw_output_path = Path(__file__).resolve().parent / "available_vehicles_raw.txt"
    raw_output_path.write_text(pprint.pformat(available), encoding="utf-8")

    vehicles_data = available.get("vehicles") if isinstance(available, dict) else None
    if vehicles_data is None:
        vehicles_data = available

    extractor = FireVehicleExtractor()
    entries = extractor.extract(vehicles_data)
    output = extractor.format_entries(entries)

    output_path.write_text(output + "\n", encoding="utf-8")
    print(f"Wrote raw response to: {raw_output_path}")
    print(f"Wrote {len(entries)} vehicles to: {output_path}")


if __name__ == "__main__":
    main()
