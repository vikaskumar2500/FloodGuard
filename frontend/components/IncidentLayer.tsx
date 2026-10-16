// MapLibre layer for incidents with distinct styles
export const incidentLayerStyle = {
  id: "incidents-layer",
  type: "circle",
  source: "incidents",
  paint: {
    "circle-radius": 6,
    "circle-color": [
      "match",
      ["get", "status"],
      "VERIFIED",
      "#ff0000", // Verified are red
      "#ffa500", // Unverified are orange
    ],
    "circle-stroke-width": 2,
    "circle-stroke-color": "#ffffff",
  },
};
