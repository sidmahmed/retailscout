export interface SelectedPoint {
  lat: number;
  lon: number;
}

export interface StagedLocation {
  id: string;
  point: SelectedPoint;
}
