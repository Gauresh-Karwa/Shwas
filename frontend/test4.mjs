import { fetchLiveStations } from './src/utils/api.js';
import { SEED_STATIONS } from './src/data/stations.js';

async function test() {
  global.BASE = "http://localhost:8000";
  global.fetch = fetch;
  
  try {
    const st = await fetchLiveStations(SEED_STATIONS);
    console.log(st);
  } catch(e) {
    console.error(e);
  }
}
test();
