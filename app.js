const logoAliases = {
  "Miami (OH)": "Miami (OH)",
  "UL Monroe": "UL Monroe"
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

async function loadTeamLogos() {
  const cells = document.querySelectorAll(".team-name");
  if (!cells.length) return;

  try {
    const response = await fetch("data/team_logos.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Local logo map unavailable");

    const logoMap = await response.json();
    const normalizedLogoMap = {};

    Object.entries(logoMap).forEach(([name, url]) => {
      normalizedLogoMap[normalize(name)] = url;
    });

    cells.forEach(cell => {
      const originalName = cell.textContent.trim();
      const lookupName = logoAliases[originalName] || originalName;
      const directLogo = logoMap[lookupName];
      const normalizedLogo = normalizedLogoMap[normalize(lookupName)];
      const logoUrl = directLogo || normalizedLogo;

      if (!logoUrl) return;

      const img = document.createElement("img");
      img.className = "team-logo";
      img.src = logoUrl;
      img.alt = "";
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

loadTeamLogos();
