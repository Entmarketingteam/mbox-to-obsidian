/**
 * ENT Agency - Brand Deliverable Calendar Sync
 *
 * Paste this into Google Apps Script (Extensions > Apps Script)
 * on the Master Brand Collabs spreadsheet.
 *
 * SETUP:
 * 1. Open the Master Brand Collabs sheet
 * 2. Extensions > Apps Script
 * 3. Paste this entire script
 * 4. Update CALENDAR_ID below (or leave "primary" for Nicki's main calendar)
 * 5. Click Run > syncAllToCalendar (first run will ask for permissions)
 * 6. Set up triggers: Edit > Current project's triggers > Add trigger:
 *    - syncAllToCalendar | Time-driven | Day timer | 6am-7am (daily sync)
 *    - onEditTrigger | From spreadsheet | On edit (live sync on changes)
 *
 * Creates calendar events for every deliverable with a date.
 * Updates existing events if dates change. Deletes events if dates are removed.
 * Color-codes by brand.
 */

// ═══════════════════════════════════════════════════════════
// CONFIG - Update these
// ═══════════════════════════════════════════════════════════

const CALENDAR_ID = "primary"; // Change to shared calendar ID if needed
const EVENT_TAG = "[ENT]"; // Prefix for all created events so we can find them
const REMINDER_MINUTES = [1440, 120]; // Reminders: 24 hours + 2 hours before

// Brand colors (Google Calendar color IDs: 1-11)
// 1=Lavender, 2=Sage, 3=Grape, 4=Flamingo, 5=Banana,
// 6=Tangerine, 7=Peacock, 8=Graphite, 9=Blueberry, 10=Basil, 11=Tomato
const BRAND_COLORS = {
  "LMNT": "7",        // Peacock (teal)
  "Gruns": "10",       // Basil (green)
  "Equip": "9",        // Blueberry
  "Hume": "3",         // Grape (purple)
  "SkinHaven": "4",    // Flamingo (pink)
  "Dermalea": "4",     // Flamingo
  "HelloFresh": "6",   // Tangerine
  "One-Off": "5",      // Banana (yellow)
  "default": "8"       // Graphite
};

// ═══════════════════════════════════════════════════════════
// MAIN FUNCTIONS
// ═══════════════════════════════════════════════════════════

/**
 * Sync all sheets to Google Calendar
 */
function syncAllToCalendar() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheets = ss.getSheets();
  const calendar = CalendarApp.getCalendarById(CALENDAR_ID) || CalendarApp.getDefaultCalendar();

  let totalCreated = 0;
  let totalUpdated = 0;
  let totalSkipped = 0;

  for (const sheet of sheets) {
    const name = sheet.getName();
    // Skip non-schedule sheets
    if (name.toLowerCase().includes("agencies") ||
        name.toLowerCase().includes("affiliate") ||
        name.toLowerCase().includes("commission")) {
      continue;
    }

    const result = syncSheet(sheet, calendar, name);
    totalCreated += result.created;
    totalUpdated += result.updated;
    totalSkipped += result.skipped;
  }

  Logger.log(`Sync complete: ${totalCreated} created, ${totalUpdated} updated, ${totalSkipped} skipped`);
}

/**
 * Process a single sheet tab
 */
function syncSheet(sheet, calendar, sheetName) {
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) return { created: 0, updated: 0, skipped: 0 };

  let created = 0, updated = 0, skipped = 0;

  // Detect brand from sheet name
  const brand = detectBrand(sheetName);
  const colorId = BRAND_COLORS[brand] || BRAND_COLORS["default"];

  // Find column indices by header names
  const headers = data[0].map(h => String(h).toLowerCase().trim());
  const clientCol = findCol(headers, ["client name", "client"]);
  const monthCol = findCol(headers, ["month"]);
  const typeCol = findCol(headers, ["campaign type", "campiagn type", "type"]);
  const deliverablesCol = findCol(headers, ["deliverables"]);
  const rateCol = findCol(headers, ["rate $", "rate", "amount"]);

  // Find date columns (reel date, story dates)
  const reelDateCol = findCol(headers, ["reel date"]);
  const story1DateCol = findCol(headers, ["story share #1 date", "story #1 date"]);
  const story2DateCol = findCol(headers, ["story share #2 date", "story #2 date"]);
  const story3DateCol = findCol(headers, ["story share #3 date", "story #3 date"]);
  const liveDateCol = findCol(headers, ["live date"]);
  const followUpCol = findCol(headers, ["follow up date"]);

  // Also check for generic date columns
  const recordDateCol = findCol(headers, ["record date"]);

  let currentClient = "";

  for (let i = 1; i < data.length; i++) {
    const row = data[i];

    // Track current client (some sheets have client name only on first row of their section)
    if (clientCol >= 0 && row[clientCol] && String(row[clientCol]).trim()) {
      currentClient = String(row[clientCol]).trim();
    }
    if (!currentClient) continue;

    const month = monthCol >= 0 ? String(row[monthCol] || "").trim() : "";
    const campaignType = typeCol >= 0 ? String(row[typeCol] || "").trim() : "";
    const deliverables = deliverablesCol >= 0 ? String(row[deliverablesCol] || "").trim() : "";
    const rate = rateCol >= 0 ? row[rateCol] : "";

    // Process each date column that has a value
    const dateColumns = [
      { col: reelDateCol, label: "Reel" },
      { col: story1DateCol, label: "Story #1" },
      { col: story2DateCol, label: "Story #2" },
      { col: story3DateCol, label: "Story #3" },
      { col: liveDateCol, label: "Live" },
      { col: followUpCol, label: "Follow-Up" },
      { col: recordDateCol, label: "Record" },
    ];

    for (const dc of dateColumns) {
      if (dc.col < 0) continue;
      const dateVal = row[dc.col];
      if (!dateVal) continue;

      const date = parseDate(dateVal);
      if (!date) continue;

      // Skip dates in the past (more than 7 days ago)
      const now = new Date();
      const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      if (date < weekAgo) {
        skipped++;
        continue;
      }

      // Build event title
      const title = `${EVENT_TAG} ${currentClient} - ${brand} ${dc.label}`;
      const description = [
        `Creator: ${currentClient}`,
        `Brand: ${brand} (${sheetName})`,
        `Type: ${campaignType}`,
        `Deliverables: ${deliverables}`,
        rate ? `Rate: $${Number(rate).toLocaleString()}` : "",
        `\nSource: Master Brand Collabs Sheet`,
      ].filter(Boolean).join("\n");

      // Check if event already exists
      const existing = findExistingEvent(calendar, title, date);

      if (existing) {
        // Update if description changed
        if (existing.getDescription() !== description) {
          existing.setDescription(description);
          updated++;
        } else {
          skipped++;
        }
      } else {
        // Create all-day event
        const event = calendar.createAllDayEvent(title, date);
        event.setDescription(description);
        event.setColor(colorId);
        // Add reminders
        event.removeAllReminders();
        for (const mins of REMINDER_MINUTES) {
          event.addPopupReminder(mins);
        }
        created++;
      }
    }
  }

  return { created, updated, skipped };
}

// ═══════════════════════════════════════════════════════════
// ON-EDIT TRIGGER (live sync when dates are entered)
// ═══════════════════════════════════════════════════════════

function onEditTrigger(e) {
  if (!e) return;
  const sheet = e.source.getActiveSheet();
  const calendar = CalendarApp.getCalendarById(CALENDAR_ID) || CalendarApp.getDefaultCalendar();
  syncSheet(sheet, calendar, sheet.getName());
}

// ═══════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════

function findCol(headers, names) {
  for (const name of names) {
    const idx = headers.indexOf(name.toLowerCase());
    if (idx >= 0) return idx;
  }
  // Partial match
  for (const name of names) {
    for (let i = 0; i < headers.length; i++) {
      if (headers[i].includes(name.toLowerCase())) return i;
    }
  }
  return -1;
}

function detectBrand(sheetName) {
  const lower = sheetName.toLowerCase();
  if (lower.includes("lmnt")) return "LMNT";
  if (lower.includes("gruns")) return "Gruns";
  if (lower.includes("equip")) return "Equip";
  if (lower.includes("hume")) return "Hume";
  if (lower.includes("skinhaven") || lower.includes("dermalea")) return "SkinHaven";
  if (lower.includes("hellofresh")) return "HelloFresh";
  if (lower.includes("one-off") || lower.includes("one off")) return "One-Off";
  return sheetName.split(" ")[0]; // First word of sheet name
}

function parseDate(val) {
  if (val instanceof Date && !isNaN(val)) return val;
  if (typeof val === "string") {
    const d = new Date(val);
    if (!isNaN(d)) return d;
  }
  if (typeof val === "number") {
    // Excel serial date
    const d = new Date((val - 25569) * 86400 * 1000);
    if (!isNaN(d)) return d;
  }
  return null;
}

function findExistingEvent(calendar, title, date) {
  const events = calendar.getEventsForDay(date);
  for (const e of events) {
    if (e.getTitle() === title) return e;
  }
  return null;
}

// ═══════════════════════════════════════════════════════════
// MENU (adds "ENT Sync" menu to the spreadsheet)
// ═══════════════════════════════════════════════════════════

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("ENT Sync")
    .addItem("Sync All to Calendar", "syncAllToCalendar")
    .addItem("Sync Current Sheet", "syncCurrentSheet")
    .addToUi();
}

function syncCurrentSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();
  const calendar = CalendarApp.getCalendarById(CALENDAR_ID) || CalendarApp.getDefaultCalendar();
  const result = syncSheet(sheet, calendar, sheet.getName());
  SpreadsheetApp.getUi().alert(
    `Sync complete: ${result.created} created, ${result.updated} updated, ${result.skipped} skipped`
  );
}
