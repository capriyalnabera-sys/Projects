/**
 * Wedding_AP - demo seed data.
 * Run:  npm run seed
 * Only seeds when the database is empty, so it won't clobber real data.
 */
const db = require('./db');

function futureDate(daysFromNow) {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString().slice(0, 10);
}

(async () => {
  await db.getDb();

  if (db.list('functions').length || db.list('guests').length) {
    console.log('Database already has data — skipping seed. (Delete wedding.db to reseed.)');
    process.exit(0);
  }

  const WED = 45; // wedding day is 45 days out

  db.setSettings({
    bride_name: 'Akansha',
    groom_name: 'Priyal',
    couple_initials: 'A & P',
    wedding_date: '2026-12-20',
    wedding_date_end: '2026-12-22',
    hashtag: '#HappilyEverAP',
    tagline: 'Two souls, one beautiful journey',
    cover_message: 'Together with our families, we joyfully invite you to share in our happiness as we begin our new life together.',
    rsvp_deadline: '2026-12-06',
    contact_name: 'Rohan (Groom\'s brother)',
    contact_phone: '+91 98765 43210',
    our_story: "Akansha and Priyal first met over chai at a friend's Diwali party in Bengaluru, a five-minute hello that turned into a five-hour conversation. Three years, countless road trips and one very nervous beachside proposal later, they are saying yes to forever, and cannot wait to begin this next chapter surrounded by the people they love most.",
    travel_info: "Venue: Taj Vivanta, Bengaluru.\nNearest airport: Kempegowda International (BLR), about 40 km away.\nRoom blocks are held for outstation guests at the Taj and the Ibis nearby; mention the Akansha & Priyal wedding when booking.\nShuttles run between the hotels and the venue for every function.",
    gift_note: "Your presence at our wedding is the greatest gift of all truly. Just come and dance with us!",
  });

  const functions = [
    { name: 'DJ Party', event_date: '2026-12-20', start_time: '20:00', dress_code: 'Party glam', theme_color: '#6f1d5b', sequence: 1, description: 'Pre-wedding warm-up with lights, beats and the dance floor all yours. 🕺' },
    { name: 'Haldi Carnival', event_date: '2026-12-21', start_time: '10:30', dress_code: 'Yellow & flowers', theme_color: '#f4c20d', sequence: 2, description: 'Turmeric, sunshine and plenty of mischief. Come get gloriously messy! 💛' },
    { name: 'Sangeet', event_date: '2026-12-21', start_time: '19:30', dress_code: 'Indo-western glam', theme_color: '#9c294b', sequence: 3, description: 'Song, dance and full-on drama. Let the performances begin! 🎶' },
    { name: 'Wedding Procession', event_date: '2026-12-22', start_time: '09:00', dress_code: 'Festive Indian', theme_color: '#c56a1a', sequence: 4, description: 'Dhol, dhamaka and the grand baraat. Dance the couple in! 🥁' },
    { name: 'Eternal Vows', event_date: '2026-12-22', start_time: '12:00', dress_code: 'Traditional elegance', theme_color: '#b8892b', sequence: 5, description: 'The moment two souls become one. Witness the sacred vows. 💍' },
  ].map(f => db.create('functions', f));

  const allFn = functions.map(f => f.id);
  const closeFamily = allFn;                 // invited to everything
  const receptionOnly = [functions[4].id];   // colleagues -> reception only
  const mainEvents = [functions[3].id, functions[4].id];

  const guests = [
    { name: 'Meera & Sanjay Kapoor', phone: '+91 98200 11111', side: 'Bride', category: 'Family', city: 'Mumbai', headcount: 2, meal_preference: 'Veg', fns: closeFamily },
    { name: 'Vikram Nair', phone: '+91 98200 22222', side: 'Groom', category: 'Friends', city: 'Bengaluru', headcount: 1, meal_preference: 'Non-veg', fns: [functions[2].id, functions[3].id, functions[4].id] },
    { name: 'Aunt Lakshmi', phone: '+91 98200 33333', side: 'Groom', category: 'Relatives', city: 'Chennai', headcount: 3, meal_preference: 'Jain', fns: closeFamily },
    { name: 'Priya Sharma', phone: '+91 98200 44444', side: 'Bride', category: 'Friends', city: 'Delhi', headcount: 2, meal_preference: 'Veg', fns: [functions[0].id, functions[2].id, functions[3].id] },
    { name: 'The Menon Family', phone: '+91 98200 55555', side: 'Bride', category: 'Relatives', city: 'Kochi', headcount: 4, meal_preference: 'Non-veg', fns: mainEvents },
    { name: 'Rahul (Office)', phone: '+91 98200 66666', side: 'Groom', category: 'Colleagues', city: 'Bengaluru', headcount: 1, meal_preference: 'No preference', fns: receptionOnly },
  ].map(g => {
    const { fns, ...rest } = g;
    const created = db.create('guests', rest);
    db.setGuestFunctions(created.id, fns);
    return created;
  });

  const vendors = [
    { name: 'Saffron Caterers', category: 'Caterer', contact_name: 'Mr. Iyer', phone: '+91 90000 10001', contract_amount: 850000, advance_paid: 200000, status: 'Booked' },
    { name: 'Blooms & Blush Decor', category: 'Decorator', contact_name: 'Nisha', phone: '+91 90000 10002', contract_amount: 450000, advance_paid: 150000, status: 'Confirmed' },
    { name: 'Lens & Light Studio', category: 'Photographer', contact_name: 'Arjun', phone: '+91 90000 10003', contract_amount: 300000, advance_paid: 100000, status: 'Booked' },
    { name: 'DJ Ricky', category: 'DJ / Sound', contact_name: 'Ricky', phone: '+91 90000 10004', contract_amount: 120000, advance_paid: 40000, status: 'Enquiry' },
    { name: 'Glow by Sneha', category: 'Makeup', contact_name: 'Sneha', phone: '+91 90000 10005', contract_amount: 90000, advance_paid: 30000, status: 'Confirmed' },
  ].map(v => db.create('vendors', v));

  [
    { category: 'Catering', item: 'Dinner buffet (all events)', estimated: 850000, actual: 850000, paid: 200000, vendor_id: vendors[0].id, status: 'Partly paid' },
    { category: 'Decor', item: 'Mandap & stage decor', estimated: 450000, actual: 450000, paid: 150000, vendor_id: vendors[1].id, status: 'Partly paid' },
    { category: 'Photography', item: 'Photo + video, 3 days', estimated: 300000, actual: 300000, paid: 100000, vendor_id: vendors[2].id, status: 'Partly paid' },
    { category: 'Music & Entertainment', item: 'Sangeet DJ & sound', estimated: 120000, actual: 0, paid: 0, vendor_id: vendors[3].id, status: 'Planned' },
    { category: 'Makeup', item: 'Bridal makeup, 3 events', estimated: 90000, actual: 90000, paid: 30000, vendor_id: vendors[4].id, status: 'Partly paid' },
    { category: 'Attire & Jewellery', item: 'Bridal lehenga', estimated: 250000, actual: 0, paid: 0, status: 'Planned' },
    { category: 'Invitations', item: 'Cards + e-invite', estimated: 60000, actual: 55000, paid: 55000, status: 'Paid' },
  ].forEach(b => db.create('budget_items', b));

  [
    { title: 'Finalise guest list & counts', category: 'Guests', owner: 'Akansha', due_date: futureDate(WED - 30), priority: 'High', status: 'In progress' },
    { title: 'Book mehndi artist', category: 'Decor', owner: 'Priya', due_date: futureDate(WED - 20), priority: 'Medium', status: 'To do' },
    { title: 'Send out invite links', category: 'Invitations', owner: 'Rohan', due_date: futureDate(WED - 21), priority: 'High', status: 'To do' },
    { title: 'Confirm room block with hotel', category: 'Logistics', owner: 'Priyal', due_date: futureDate(WED - 25), priority: 'High', status: 'Done' },
    { title: 'Pandit booking & muhurat', category: 'Rituals', owner: 'Family', due_date: futureDate(WED - 40), priority: 'High', status: 'Done' },
  ].forEach(t => db.create('tasks', t));

  const rooms = [
    { hotel: 'Taj Vivanta', room_number: '201', room_type: 'Double', capacity: 2 },
    { hotel: 'Taj Vivanta', room_number: '202', room_type: 'Family', capacity: 4 },
    { hotel: 'Taj Vivanta', room_number: '203', room_type: 'Twin', capacity: 2 },
  ].map(r => db.create('rooms', r));

  db.create('room_allocations', { guest_id: guests[0].id, room_id: rooms[0].id, check_in: futureDate(WED - 2), check_out: futureDate(WED + 1) });
  db.create('room_allocations', { guest_id: guests[2].id, room_id: rooms[1].id, check_in: futureDate(WED - 2), check_out: futureDate(WED + 2) });

  db.create('travel', { guest_id: guests[0].id, direction: 'Arrival', mode: 'Flight', detail: '6E-234', datetime: futureDate(WED - 2) + 'T14:30', location: 'BLR Airport', pickup_needed: 1, coordinator: 'Rohan', status: 'Arranged' });
  db.create('travel', { guest_id: guests[3].id, direction: 'Arrival', mode: 'Train', detail: 'Rajdhani', datetime: futureDate(WED - 2) + 'T08:00', location: 'KSR Bengaluru', pickup_needed: 1, coordinator: 'Vikram', status: 'Pending' });

  [
    { title: 'Bride & bridesmaids opening', function_id: functions[2].id, performers: 'Akansha, Priya, Meera', song: 'Dola Re Dola', sequence: 1, duration: '4 min', status: 'Rehearsing' },
    { title: 'Groom\'s squad', function_id: functions[2].id, performers: 'Priyal, Vikram, Rahul', song: 'The Breakup Song', sequence: 2, duration: '3 min', status: 'Idea' },
    { title: 'Couple\'s dance', function_id: functions[2].id, performers: 'Akansha & Priyal', song: 'Tum Se Hi', sequence: 3, duration: '3 min', status: 'Idea' },
  ].forEach(p => db.create('dance_performances', p));

  [
    { person: 'Akansha', function_id: functions[3].id, outfit: 'Red bridal lehenga', color: 'Red', status: 'To buy' },
    { person: 'Priyal', function_id: functions[3].id, outfit: 'Ivory sherwani', color: 'Ivory', status: 'Ordered' },
    { person: 'Akansha', function_id: functions[1].id, outfit: 'Yellow suit', color: 'Yellow', status: 'Ready' },
  ].forEach(o => db.create('outfits', o));

  db.create('gifts_give', { occasion: 'Return gift (Reception)', recipient: 'All guests', item: 'Silver diya + sweets box', quantity: 200, cost: 400, status: 'To buy' });
  db.create('gifts_received', { from_name: 'Meera & Sanjay Kapoor', guest_id: guests[0].id, item: 'Silver dinner set', amount: 0, function_id: functions[3].id, thank_you_sent: 0 });

  console.log('✅ Seeded demo wedding data.');
  console.log('   Guests with invite links:');
  db.list('guests').forEach(g => console.log(`   - ${g.name}: /i/${g.invite_token}`));
  process.exit(0);
})();
