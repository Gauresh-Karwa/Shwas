async function test() {
  const seedStations = [
    { id: 'bandra-kurla-complex-mumbai-iitm', lat: 19.053536, lon: 72.84643 },
    { id: 'kurla-mumbai-mpcb', lat: 19.0863, lon: 72.8888 }
  ];
  
  let validStations = [];
  await Promise.allSettled(
    seedStations.map(async (s) => {
      try {
        const url = `http://localhost:8000/api/interpolate?lat=${s.lat}&lon=${s.lon}`;
        const res = await fetch(url);
        if (res.ok) {
          const data = await res.json();
          console.log(data);
          if (data && data.estimated_aqi > 0) {
            validStations.push({ id: s.id, aqi: Math.round(data.estimated_aqi) });
          }
        }
      } catch (e) { console.error(e) }
    })
  );
  console.log("Valid stations:", validStations);
}
test();
