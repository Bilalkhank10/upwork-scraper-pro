/**
 * Upwork Scraper PRO → Google Sheets Auto-Sync
 * Paste this in: Google Sheets → Extensions → Apps Script
 * 
 * How it works:
 * Apify Actor (webhookUrl) → POSTs JSON to this script's Web App URL → Sheet updates → Looker Studio auto-refreshes
 * 
 * Setup:
 * 1. Open your Google Sheet (the one connected to Looker Studio)
 * 2. Extensions → Apps Script → Delete default Code.gs → Paste this file → Save
 * 3. Deploy → New deployment → Web app → Execute as: Me, Who has access: Anyone → Copy Web App URL
 * 4. Apify Actor Input → webhookUrl = YOUR_WEB_APP_URL → webhookHeaders = {} → Run
 * 
 * Alternative (no webhook): Use Apify's Google Sheets integration directly - this script is for advanced webhook mode
 */

const SHEET_NAME = "Upwork_Raw_Data"; // Must match Excel tab
const HEADER_ROW = 1;

function doPost(e) {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
    if (!sheet) throw new Error("Sheet '" + SHEET_NAME + "' not found");

    // Parse payload from Apify webhook: {metadata, items}
    const body = JSON.parse(e.postData.contents);
    const items = body.items || body.data || [];
    const metadata = body.metadata || {};

    if (items.length === 0) {
      return jsonResponse({status: "ok", message: "No items", received: 0});
    }

    // Ensure headers exist (create if first run)
    if (sheet.getLastRow() === 0) {
      const headers = Object.keys(items[0]);
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      sheet.getRange(1, 1, 1, headers.length)
        .setBackground("#14A800")
        .setFontColor("#FFFFFF")
        .setFontWeight("bold");
      sheet.setFrozenRows(1);
    }

    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    
    // Optional: Clear old data if you want only latest run (uncomment next 2 lines)
    // sheet.getRange(2, 1, sheet.getLastRow(), sheet.getLastColumn()).clearContent();

    // Incremental append: Add new rows at bottom
    // For true incremental (dedupe by jobId), we check existing jobIds
    const existingIds = new Set();
    if (sheet.getLastRow() > 1) {
      const idCol = headers.indexOf("jobId") + 1;
      if (idCol > 0) {
        const ids = sheet.getRange(2, idCol, sheet.getLastRow() - 1, 1).getValues().flat();
        ids.forEach(id => existingIds.add(String(id)));
      }
    }

    const rowsToAdd = [];
    let skipped = 0;
    for (const item of items) {
      const jobId = String(item.jobId || item.job_id || "");
      if (existingIds.has(jobId) && !item.changeType /* if incremental already */) {
        // Skip duplicates unless it's an UPDATED
        if (item.changeType === "NEW" || item.changeType === "UPDATED" || item.changeType === "REAPPEARED") {
          // Allow updated to pass - we could update existing row instead
        } else {
          skipped++;
          continue;
        }
      }
      const row = headers.map(h => {
        let v = item[h];
        // Handle arrays (skills)
        if (Array.isArray(v)) return v.join(", ");
        // Handle objects
        if (typeof v === "object" && v !== null) return JSON.stringify(v);
        return v !== undefined ? v : "";
      });
      rowsToAdd.push(row);
    }

    if (rowsToAdd.length > 0) {
      sheet.getRange(sheet.getLastRow() + 1, 1, rowsToAdd.length, headers.length).setValues(rowsToAdd);
      
      // Auto-format new rows: AI Score coloring
      const scoreCol = headers.indexOf("aiLeadScore") + 1;
      const tierCol = headers.indexOf("clientTier") + 1;
      if (scoreCol > 0) {
        const startRow = sheet.getLastRow() - rowsToAdd.length + 1;
        for (let i = 0; i < rowsToAdd.length; i++) {
          const score = Number(rowsToAdd[i][scoreCol - 1]);
          const range = sheet.getRange(startRow + i, scoreCol);
          if (score >= 85) range.setBackground("#14A800").setFontColor("#FFFFFF").setFontWeight("bold");
          else if (score >= 70) range.setBackground("#F59E0B").setFontColor("#FFFFFF").setFontWeight("bold");
          else if (score < 50) range.setBackground("#EF4444").setFontColor("#FFFFFF").setFontWeight("bold");
        }
      }
      if (tierCol > 0) {
        const startRow = sheet.getLastRow() - rowsToAdd.length + 1;
        for (let i = 0; i < rowsToAdd.length; i++) {
          const tier = rowsToAdd[i][tierCol - 1];
          const range = sheet.getRange(startRow + i, tierCol);
          if (tier === "PREMIUM") range.setBackground("#14A800").setFontColor("#FFFFFF").setFontWeight("bold");
          else if (tier === "Risky") range.setBackground("#EF4444").setFontColor("#FFFFFF").setFontWeight("bold");
        }
      }
    }

    // Log to sheet's second tab for debugging
    logToSheet(`Added ${rowsToAdd.length} rows, skipped ${skipped} dupes | Query: ${metadata.query || 'n/a'} | Total: ${items.length}`);

    return jsonResponse({
      status: "success",
      received: items.length,
      added: rowsToAdd.length,
      skipped: skipped,
      sheet: SHEET_NAME,
      lastRow: sheet.getLastRow()
    });

  } catch (err) {
    return jsonResponse({status: "error", message: err.toString()});
  }
}

function doGet(e) {
  // Health check: visit Web App URL in browser
  return jsonResponse({status: "ok", message: "Upwork Scraper webhook is live! Use POST to push data.", sheet: SHEET_NAME});
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj, null, 2)).setMimeType(ContentService.MimeType.JSON);
}

function logToSheet(msg) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let logSheet = ss.getSheetByName("_Logs");
    if (!logSheet) {
      logSheet = ss.insertSheet("_Logs");
      logSheet.getRange(1,1,1,2).setValues([["Timestamp","Message"]]).setBackground("#374151").setFontColor("#FFFFFF").setFontWeight("bold");
    }
    logSheet.appendRow([new Date().toISOString(), msg]);
  } catch(e) {}
}

/**
 * TEST: Run this manually from Apps Script editor to test
 */
function testPush() {
  const mock = {
    postData: {
      contents: JSON.stringify({
        metadata: {query: "shopify developer", total: 2},
        items: [
          {jobId: "9999991", title: "Test Shopify Job - PREMIUM", jobType: "FIXED", budgetAmount: 2000, clientCountry: "United States", clientTotalSpent: 50000, clientPaymentVerified: true, clientRating: 4.9, totalApplicants: 3, aiLeadScore: 95, clientTier: "PREMIUM", url: "https://upwork.com/jobs/~0991", publishTime: new Date().toISOString()},
          {jobId: "9999992", title: "Test Data Entry - Risky", jobType: "HOURLY", hourlyBudgetMin: 5, hourlyBudgetMax: 10, clientCountry: "Pakistan", clientTotalSpent: 0, clientPaymentVerified: false, clientRating: 0, totalApplicants: 40, aiLeadScore: 15, clientTier: "Risky", url: "https://upwork.com/jobs/~0992", publishTime: new Date().toISOString()}
        ]
      })
    }
  };
  const res = doPost(mock);
  Logger.log(res.getContent());
}
