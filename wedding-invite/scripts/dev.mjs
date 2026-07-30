import { serve } from './lib/serve.mjs';

const port = Number(process.env.PORT || 4321);
// 0.0.0.0 so you can open it on your phone over the same wifi.
const { url } = await serve(port, '0.0.0.0');

console.log(`\n  Invite running at ${url}`);
console.log('  On your phone: same wifi, then open http://<your-computer-ip>:' + port);
console.log('  Test on the phone after every change, not at the end.\n');
