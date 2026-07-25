"use client";

/**
 * The primary product surface: full-height MapLibre map with the
 * precomputed suitability hexes streamed as vector tiles from
 * /api/v1/tiles/suitability/{profile}/{z}/{x}/{y}.mvt (source layer
 * "suitability"; feature props cell_id, total_score, confidence_score).
 *
 * Basemap is OpenFreeMap "positron" — key-free, light neutral, matching
 * the civic-intelligence theme. Score ramp colors are read from the CSS
 * tokens at runtime (lib/tokens.ts) so globals.css remains the single
 * source of truth.
 */

import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";

import "maplibre-gl/dist/maplibre-gl.css";

import { suitabilityTileUrl } from "@/lib/api/client";
import { useCoverage } from "@/lib/api/hooks";
import type { SelectedPoint, StagedLocation } from "@/lib/locations";
import type { BusinessProfile } from "@/lib/api/types";
import { cssVar, scoreColors } from "@/lib/tokens";

const MELBOURNE_CBD: [number, number] = [144.9631, -37.8136];
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
const SOURCE_ID = "suitability";
const SOURCE_LAYER = "suitability";

interface Props {
  activeLocation: StagedLocation | null;
  focusPoint: SelectedPoint | null;
  profile: BusinessProfile;
  staged: StagedLocation[];
  onSelect: (point: SelectedPoint) => void;
}

function scorePaint(): maplibregl.ExpressionSpecification {
  const c = scoreColors();
  // Band midpoints per ui-context.md (0-33 / 34-66 / 67-100) with a
  // linear ramp between them so adjacent hexes read as a gradient.
  return [
    "interpolate",
    ["linear"],
    ["get", "total_score"],
    20,
    c.low,
    50,
    c.mid,
    80,
    c.high,
  ];
}

export function SuitabilityMap({
  activeLocation,
  focusPoint,
  profile,
  staged,
  onSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRefs = useRef<maplibregl.Marker[]>([]);
  const profileRef = useRef(profile);
  // onSelect via ref so the map isn't torn down when the parent re-renders.
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);
  const { data: coverage } = useCoverage();

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      center: MELBOURNE_CBD,
      zoom: 13,
      minZoom: 10,
      maxZoom: 18,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    map.on("load", () => {
      map.addSource(SOURCE_ID, {
        type: "vector",
        tiles: [suitabilityTileUrl(profileRef.current)],
        minzoom: 10,
        maxzoom: 16,
        promoteId: "cell_id",
      });
      map.addLayer({
        id: "suitability-fill",
        type: "fill",
        source: SOURCE_ID,
        "source-layer": SOURCE_LAYER,
        // A withheld (null) score must not be painted as if it were a
        // score (invariant 4) — MVT omits null properties, so such cells
        // simply lack total_score and show only the outline.
        filter: ["has", "total_score"],
        paint: {
          "fill-color": scorePaint(),
          "fill-opacity": [
            "interpolate",
            ["linear"],
            ["zoom"],
            11,
            0.45,
            16,
            0.3,
          ],
        },
      });
      map.addLayer({
        id: "suitability-outline",
        type: "line",
        source: SOURCE_ID,
        "source-layer": SOURCE_LAYER,
        paint: {
          "line-color": cssVar("--bg-surface"),
          "line-opacity": 0.35,
          "line-width": 0.5,
        },
      });
    });

    map.on("click", (e) => {
      onSelectRef.current({ lat: e.lngLat.lat, lon: e.lngLat.lng });
    });
    map.on("mouseenter", "suitability-fill", () => {
      map.getCanvas().style.cursor = "crosshair";
    });
    map.on("mouseleave", "suitability-fill", () => {
      map.getCanvas().style.cursor = "";
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Profile change: swap the tile template in place (no source rebuild).
  useEffect(() => {
    profileRef.current = profile;
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource(SOURCE_ID);
    if (source && source.type === "vector") {
      (source as maplibregl.VectorTileSource).setTiles([suitabilityTileUrl(profile)]);
    }
  }, [profile]);

  // First coverage load: frame the municipality.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !coverage) return;
    const [minLon, minLat, maxLon, maxLat] = coverage.bounds;
    map.fitBounds(
      [
        [minLon, minLat],
        [maxLon, maxLat],
      ],
      { padding: 48, duration: 800 },
    );
  }, [coverage]);

  // Search selections should bring the result into view; ordinary map
  // clicks already happen in the current viewport and do not recenter.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !focusPoint) return;
    map.easeTo({
      center: [focusPoint.lon, focusPoint.lat],
      zoom: Math.max(map.getZoom(), 15),
      duration: 700,
    });
  }, [focusPoint]);

  // Numbered staged markers anchor comparison columns to the map. A
  // currently inspected, unstaged location gets an unnumbered ring.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRefs.current.forEach((marker) => marker.remove());
    const activeIsStaged = staged.some(
      (location) => location.id === activeLocation?.id,
    );
    const visibleLocations =
      activeLocation && !activeIsStaged ? [...staged, activeLocation] : staged;

    markerRefs.current = visibleLocations.map((location) => {
      const stagedIndex = staged.findIndex(
        (candidate) => candidate.id === location.id,
      );
      const active = location.id === activeLocation?.id;
      const size = active ? 25 : 21;
      const el = document.createElement("div");
      el.textContent = stagedIndex >= 0 ? String(stagedIndex + 1) : "";
      el.setAttribute(
        "aria-label",
        stagedIndex >= 0 ? `Location ${stagedIndex + 1}` : "Selected location",
      );
      el.style.cssText = [
        `width:${size}px`,
        `height:${size}px`,
        "display:flex",
        "align-items:center",
        "justify-content:center",
        "border-radius:9999px",
        `border:${active ? 3 : 2}px solid var(--accent-primary)`,
        "background:var(--bg-surface)",
        "color:var(--accent-primary)",
        "font:600 10px var(--font-sans)",
        "box-shadow:0 1px 4px color-mix(in srgb, var(--text-primary) 35%, transparent)",
      ].join(";");
      return new maplibregl.Marker({ element: el })
        .setLngLat([location.point.lon, location.point.lat])
        .addTo(map);
    });
  }, [activeLocation, staged]);

  // Inline style, not Tailwind classes: maplibre-gl.css is unlayered and
  // its .maplibregl-map { position: relative } beats Tailwind's layered
  // .absolute in the cascade, collapsing the container to height 0.
  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
