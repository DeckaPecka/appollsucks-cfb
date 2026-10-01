const logoAliases = {
  "Miami (OH)": "Miami (OH)",
  "Hawai'i": "Hawaii",
  "San José State": "San Jose State",
  "UTEP": "UTEP",
  "UL Monroe": "UL Monroe",
  "Massachusetts": "Massachusetts",
  "North Dakota State": "North Dakota State",
  "James Madison": "James Madison"
};

function normalize(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/[().&,]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function loadTeamLogos() {
  const cells = document.querySelectorAll(".team-name");
  if (!cells.length) return;

  try {
    const response = await fetch("https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000");
    if (!response.ok) throw new Error("Logo service unavailable");

    const payload = await response.json();
    const teams = payload?.sports?.[0]?.leagues?.[0]?.teams || [];
    const logoMap = new Map();

    teams.forEach(entry => {
      const team = entry.team || entry;
      const name = team.displayName || team.name;
      const logo = team.logos?.[0]?.href;
      if (name && logo) logoMap.set(normalize(name), logo);
    });

    cells.forEach(cell => {
      const originalName = cell.textContent.trim();
      const lookupName = logoAliases[originalName] || originalName;
      const logo = logoMap.get(normalize(lookupName));
      if (!logo) return;

      const img = document.createElement("img");
      img.className = "team-logo";
      img.src = logo;
      img.alt = "";
      img.width = 32;
      img.height = 32;
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";

      cell.prepend(img);
      cell.classList.add("has-logo");
    });
  } catch (error) {
    console.warn("Team logos could not be loaded:", error);
  }
}

loadTeamLogos();
