async function test() {
  const seedStations = [
    { id: 'bandra-kurla-complex-mumbai-iitm' },
    { id: 'kurla-mumbai-mpcb' },
    { id: 'borivali-east-mumbai-iitm' }
  ];
  
  let validStations = [];
  await Promise.allSettled(
    seedStations.map(async (s) => {
      try {
        const url = `http://localhost:8000/api/forecast/${encodeURIComponent(s.id)}?steps=1`;
        const res = await fetch(url);
        if (res.ok) {
          const data = await res.json();
          console.log(data);
          const fc = data.forecast?.[0] ?? (Array.isArray(data) ? data[0] : null);
          if (fc && fc.aqi > 0) {
            validStations.push({ id: s.id, aqi: fc.aqi });
          }
        }
      } catch (e) { console.error(e) }
    })
  );
  console.log("Valid stations:", validStations);
}
test();
