const logoAliases = {
  "Miami (OH)": "Miami (OH)",
  "UL Monroe": "UL Monroe",
  "San Jose State": "https://commons.wikimedia.org/wiki/Special:Redirect/file/San%20Jose%20State%20Spartans%20logo.svg",
  "Hawaii": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Hawaii_Warriors_logo.svg"
};

function normalize(name) {
  return String(name || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/[().&,]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function rankGap(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const gap = Number(value);
  if (gap === 0) return "—";
  const label = gap > 0 ? "+" + gap : String(gap);
  return '<span class="move same">' + label + "</span>";
}

async function loadRankings() {
  const response = await fetch("data/rankings.json", { cache: "no-store" });
  if (!response.ok) throw new Error("Rankings data is unavailable");
  const data = await response.json();
  const rows = Array.isArray(data.rankings) ? data.rankings : [];
  const leader = rows[0];

  const updated = document.getElementById("updated-label");
  if (updated) {
    const date = data.generatedAt ? new Date(data.generatedAt).toLocaleString() : "Unknown";
    updated.textContent = "Updated " + date + " • " + rows.length + " teams";
  }

  if (leader) {
    document.getElementById("leader-rank").textContent = "#" + leader.rank;
    document.getElementById("leader-team").textContent = leader.team;
    document.getElementById("leader-record").textContent =
      leader.wins + "–" + leader.losses + " • " + (leader.conference || "Independent");
    document.getElementById("leader-rating").textContent = Number(leader.rating).toFixed(3);
  }

  const body = document.getElementById("rankings-body");
  if (body) {
    body.innerHTML = rows.map(row => {
      const gap = row.rankDifferenceVsFPI;
      return '<tr>' +
        '<td>' + escapeHtml(row.rank) + '</td>' +
        '<td><div class="team-name">' + escapeHtml(row.team) + '</div><div class="team-sub">' + escapeHtml(row.conference || "") + '</div></td>' +
        '<td>' + escapeHtml(row.wins + "-" + row.losses) + '</td>' +
        '<td>' + escapeHtml(row.conference || "—") + '</td>' +
        '<td>' + (row.fpiRank == null ? "—" : "#" + escapeHtml(row.fpiRank)) + '</td>' +
        '<td>' + rankGap(gap) + '</td>' +
        '<td class="rating">' + Number(row.rating).toFixed(3) + '</td>' +
        '</tr>';
    }).join("");
  }

  const snapshotTeams = document.getElementById("snapshot-teams");
  if (snapshotTeams) snapshotTeams.textContent = data.teamCount ?? rows.length;
  const comparison = data.fpiComparison || {};
  const snapshotFpi = document.getElementById("snapshot-fpi");
  const snapshotGap = document.getElementById("snapshot-gap");
  if (snapshotFpi) snapshotFpi.textContent = comparison.matchedTeams ?? "—";
  if (snapshotGap) {
    snapshotGap.textContent = comparison.meanAbsoluteRankDifference == null
      ? "Pending"
      : Number(comparison.meanAbsoluteRankDifference).toFixed(1);
  }

  const methodCopy = document.querySelector(".method-copy");
  if (methodCopy && comparison.spearmanRankCorrelation != null) {
    const note = document.createElement("p");
    note.className = "small";
    note.id = "fpi-correlation";
    note.textContent = "Current rank correlation with FPI (Spearman): " +
      Number(comparison.spearmanRankCorrelation).toFixed(3) + ". " +
      (comparison.note || "");
    const existing = document.getElementById("fpi-correlation");
    if (existing) existing.remove();
    methodCopy.appendChild(note);
  }
}

async function loadTeamLogos() {
  try {
    const [logoResponse, rankingResponse] = await Promise.all([
      fetch("data/team_logos.json", { cache: "no-store" }),
      fetch("data/rankings.json", { cache: "no-store" })
    ]);
    if (!logoResponse.ok || !rankingResponse.ok) throw new Error("Team data unavailable");
    const logoMap = await logoResponse.json();
    const data = await rankingResponse.json();
    const normalizedLogoMap = {};
    Object.entries(logoMap).forEach(([name, url]) => {
      normalizedLogoMap[normalize(name)] = url;
    });

    document.querySelectorAll(".team-name").forEach(cell => {
      if (cell.querySelector("img.team-logo")) return;
      const originalName = cell.textContent.trim();
      const alias = logoAliases[originalName];
      const logoUrl = alias && alias.startsWith("http")
        ? alias
        : logoMap[alias || originalName] || normalizedLogoMap[normalize(alias || originalName)];
      if (!logoUrl) return;

      const img = document.createElement("img");
      img.className = "team-logo";
      img.src = logoUrl;
      img.alt = originalName + " logo";
      img.width = 32;
      img.height = 32;
      img.loading = "lazy";
      img.onerror = () => img.remove();
      cell.prepend(img);
      cell.classList.add("has-logo");
    });
  } catch (error) {
    console.warn("Team logos could not be loaded:", error);
  }
}

loadRankings()
  .then(loadTeamLogos)
  .catch(error => {
    console.error("Rankings could not be loaded:", error);
    const body = document.getElementById("rankings-body");
    if (body) body.innerHTML = '<tr><td colspan="7">Rankings data could not be loaded. Please try again later.</td></tr>';
  });
