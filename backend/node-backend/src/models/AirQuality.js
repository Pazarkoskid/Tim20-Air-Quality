class AirQuality {
    constructor(id, location, pm10, pm2_5, co, no2, timestamp) {
        this.id = id;
        this.location = location;
        this.pm10 = pm10;
        this.pm2_5 = pm2_5;
        this.co = co;
        this.no2 = no2;
        this.timestamp = timestamp;
    }
}

module.exports = AirQuality;