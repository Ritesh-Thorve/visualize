"""
geoplot.py - Geographic Visualization Module
-------------------------------------------

This module generates interactive 3D visualizations of simulation data using CesiumJS.
It creates both GeoJSON data files and HTML visualization files that can be viewed in a web browser.

Key Features:
- Renders time-series data on a 3D globe
- Supports both color and size-based visual encoding
- Generates self-contained HTML files with embedded data

Example Usage:
    from agent_torch.visualize import GeoPlot
    
    # After setting up simulation...
    visualizer = GeoPlot(config, {
        'cesium_token': "your_api_token",
        'step_time': 3600,
        'coordinates': "agents/locations",
        'feature': "agents/activity_level",
        'visualization_type': "color"  # or "size"
    })
    
    # During simulation run:
    visualizer.render(simulation_state_trajectory)
"""

import re
import json
import pandas as pd
import numpy as np
from string import Template
from agent_torch.core.helpers import get_by_path

# HTML template with embedded JavaScript for Cesium visualization
# Uses string.Template placeholders ($variable) for dynamic content
geoplot_template = """<!doctype html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AgentTorch Geo-Visualization</title>
    <!-- CesiumJS libraries -->
    <script src="https://cesium.com/downloads/cesiumjs/releases/1.95/Build/Cesium/Cesium.js"></script>
    <link href="https://cesium.com/downloads/cesiumjs/releases/1.95/Build/Cesium/Widgets/widgets.css" rel="stylesheet" />
    <style>
        #cesiumContainer { width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="cesiumContainer"></div>
    <script>
        // Initialize Cesium with provided access token
        Cesium.Ion.defaultAccessToken = '$accessToken';
        const viewer = new Cesium.Viewer('cesiumContainer');
        
        /**
         * Color interpolation between two Cesium colors
         * @param {Cesium.Color} color1 - Start color
         * @param {Cesium.Color} color2 - End color
         * @param {number} factor - Interpolation factor (0-1)
         */
        function interpolateColor(color1, color2, factor) {
            const result = new Cesium.Color();
            result.red = color1.red + factor * (color2.red - color1.red);
            result.green = color1.green + factor * (color2.green - color1.green);
            result.blue = color1.blue + factor * (color2.blue - color1.blue);
            result.alpha = '$visualType' == 'size' ? 0.2 : 
                          color1.alpha + factor * (color2.alpha - color1.alpha);
            return result;
        }

        /**
         * Gets visualization color based on normalized value
         * @param {number} value - Current data value
         * @param {number} min - Minimum value in dataset
         * @param {number} max - Maximum value in dataset
         */
        function getColor(value, min, max) {
            const factor = (value - min) / (max - min);
            return interpolateColor(Cesium.Color.BLUE, Cesium.Color.RED, factor);
        }

        /**
         * Gets point size based on normalized value (for size encoding)
         * @param {number} value - Current data value
         * @param {number} min - Minimum value in dataset
         * @param {number} max - Maximum value in dataset
         */
        function getPixelSize(value, min, max) {
            const factor = (value - min) / (max - min);
            return 100 * (1 + factor);  // Scales from 100 to 200 pixels
        }

        /**
         * Processes GeoJSON into time-series format
         * @param {object} geoJsonData - Input GeoJSON data
         * @returns {object} Processed data with time series and value bounds
         */
        function processTimeSeriesData(geoJsonData) {
            const timeSeriesMap = new Map();
            let [minValue, maxValue] = [Infinity, -Infinity];

            geoJsonData.features.forEach((feature) => {
                const time = Cesium.JulianDate.fromIso8601(feature.properties.time);
                const value = feature.properties.value;
                const coordinates = feature.geometry.coordinates;

                if (!timeSeriesMap.has(feature.properties.id)) {
                    timeSeriesMap.set(feature.properties.id, []);
                }
                timeSeriesMap.get(feature.properties.id).push({ time, value, coordinates });

                minValue = Math.min(minValue, value);
                maxValue = Math.max(maxValue, value);
            });

            return { timeSeriesMap, minValue, maxValue };
        }

        /**
         * Creates Cesium entities from time-series data
         * @param {object} timeSeriesData - Processed time-series data
         * @param {Cesium.JulianDate} startTime - Visualization start time
         * @param {Cesium.JulianDate} stopTime - Visualization end time
         */
        function createTimeSeriesEntities(timeSeriesData, startTime, stopTime) {
            const dataSource = new Cesium.CustomDataSource('AgentTorch Simulation');

            for (const [id, timeSeries] of timeSeriesData.timeSeriesMap) {
                const entity = new Cesium.Entity({
                    id: id,
                    availability: new Cesium.TimeIntervalCollection([
                        new Cesium.TimeInterval({ start: startTime, stop: stopTime })
                    ]),
                    position: new Cesium.SampledPositionProperty(),
                    point: {
                        pixelSize: '$visualType' == 'size' ? new Cesium.SampledProperty(Number) : 10,
                        color: new Cesium.SampledProperty(Cesium.Color),
                    },
                    properties: { value: new Cesium.SampledProperty(Number) },
                });

                timeSeries.forEach(({ time, value, coordinates }) => {
                    const position = Cesium.Cartesian3.fromDegrees(coordinates[0], coordinates[1]);
                    entity.position.addSample(time, position);
                    entity.properties.value.addSample(time, value);
                    entity.point.color.addSample(time, getColor(value, timeSeriesData.minValue, timeSeriesData.maxValue));
                    
                    if ('$visualType' == 'size') {
                        entity.point.pixelSize.addSample(
                            time,
                            getPixelSize(value, timeSeriesData.minValue, timeSeriesData.maxValue)
                        );
                    }
                });

                dataSource.entities.add(entity);
            }
            return dataSource;
        }

        // Main visualization execution
        const geoJsons = $data;
        const start = Cesium.JulianDate.fromIso8601('$startTime');
        const stop = Cesium.JulianDate.fromIso8601('$stopTime');

        // Configure Cesium timeline
        viewer.clock.startTime = start.clone();
        viewer.clock.stopTime = stop.clone();
        viewer.clock.currentTime = start.clone();
        viewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP;
        viewer.clock.multiplier = 3600; // 1 simulated hour per real second

        viewer.timeline.zoomTo(start, stop);

        // Add all data sources to viewer
        for (const geoJsonData of geoJsons) {
            const timeSeriesData = processTimeSeriesData(geoJsonData);
            const dataSource = createTimeSeriesEntities(timeSeriesData, start, stop);
            viewer.dataSources.add(dataSource);
            viewer.zoomTo(dataSource);
        }
    </script>
</body>
</html>"""

def read_var(state, var_path):
    """Helper function to access nested dictionary values using path strings
    
    Args:
        state: The dictionary/state object to access
        var_path: Path string (e.g., "agents/location/coordinates")
    
    Returns:
        The value at the specified path
    """
    return get_by_path(state, re.split("/", var_path))


class GeoPlot:
    """Geographic visualization engine for AgentTorch simulations
    
    Attributes:
        config: Simulation configuration dictionary
        cesium_token: Cesium Ion API access token
        step_time: Time between simulation steps (in seconds)
        entity_position: Path to coordinate data in state
        entity_property: Path to feature values in state
        visualization_type: Either 'color' or 'size' encoding
    """

    def __init__(self, config, options):
        """Initialize the geographic visualizer
        
        Args:
            config: Simulation configuration dictionary
            options: Visualization parameters including:
                - cesium_token: Cesium API token
                - step_time: Seconds per simulation step
                - coordinates: Path to location data
                - feature: Path to visualization values
                - visualization_type: 'color' or 'size'
        """
        self.config = config
        self.cesium_token = options["cesium_token"]
        self.step_time = options["step_time"]
        self.entity_position = options["coordinates"]
        self.entity_property = options["feature"]
        self.visualization_type = options.get("visualization_type", "color")

    def render(self, state_trajectory):
        """Generate visualization files from simulation data
        
        Creates two files:
        1. GeoJSON file containing all visualization data
        2. HTML file with embedded Cesium visualization
        
        Args:
            state_trajectory: List of simulation states over time
        """
        # Initialize data containers
        coordinates = []
        feature_values = []
        sim_name = self.config["simulation_metadata"]["name"]
        
        # Output filenames
        geojson_file = f"{sim_name}.geojson"
        html_file = f"{sim_name}.html"

        # Extract coordinates and values from each state
        for state in state_trajectory[:-1]:  # Exclude final state if incomplete
            final_state = state[-1]  # Get terminal state of this trajectory
            
            # Read coordinates and convert to list format
            coordinates = np.array(
                read_var(final_state, self.entity_position)
            ).tolist()
            
            # Read feature values and flatten to 1D list
            feature_values.append(
                np.array(
                    read_var(final_state, self.entity_property)
                ).flatten().tolist()
            )

        # Generate timestamps for the entire simulation
        start_time = pd.Timestamp.utcnow()
        total_steps = (
            self.config["simulation_metadata"]["num_episodes"] *
            self.config["simulation_metadata"]["num_steps_per_episode"]
        )
        timestamps = [
            start_time + pd.Timedelta(seconds=i * self.step_time)
            for i in range(total_steps)
        ]

        # Convert simulation data to GeoJSON format
        geojson_data = []
        for idx, coord in enumerate(coordinates):
            features = []
            for time, values in zip(timestamps, feature_values):
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [coord[1], coord[0]]  # GeoJSON order: [long, lat]
                    },
                    "properties": {
                        "id": f"entity_{idx}",
                        "value": values[idx],
                        "time": time.isoformat()
                    }
                })
            
            geojson_data.append({
                "type": "FeatureCollection",
                "features": features
            })

        # Save GeoJSON data to file
        with open(geojson_file, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)

        # Generate and save HTML visualization
        template = Template(geoplot_template)
        html_content = template.substitute({
            "accessToken": self.cesium_token,
            "startTime": timestamps[0].isoformat(),
            "stopTime": timestamps[-1].isoformat(),
            "data": json.dumps(geojson_data),
            "visualType": self.visualization_type
        })

        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
