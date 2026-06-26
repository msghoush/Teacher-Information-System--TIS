(() => {
    "use strict";

    const OTHER_VALUE = "__other__";
    const requestCache = new Map();

    const getItems = (url) => {
        if (!requestCache.has(url)) {
            const request = fetch(url, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            })
                .then(async (response) => {
                    const payload = await response.json();
                    if (!response.ok) {
                        throw new Error(payload.detail || "Unable to load locations.");
                    }
                    return payload.items || [];
                })
                .catch((error) => {
                    requestCache.delete(url);
                    throw error;
                });
            requestCache.set(url, request);
        }
        return requestCache.get(url);
    };

    const appendOption = (select, value, label, disabled = false) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = label;
        option.disabled = disabled;
        select.appendChild(option);
        return option;
    };

    const replaceOptions = (select, placeholder, items, valueKey, includeOther = false) => {
        select.replaceChildren();
        appendOption(select, "", placeholder);
        items.forEach((item) => appendOption(select, item[valueKey], item.name));
        if (includeOther) {
            appendOption(select, OTHER_VALUE, "Other / manual entry");
        }
    };

    const findValueByLabel = (select, label) => {
        const normalizedLabel = String(label || "").trim().toLocaleLowerCase();
        if (!normalizedLabel) {
            return "";
        }
        const match = Array.from(select.options).find(
            (option) => option.textContent.trim().toLocaleLowerCase() === normalizedLabel
        );
        return match ? match.value : "";
    };

    const setManualInput = (input, visible, value, locked) => {
        input.hidden = !visible;
        input.disabled = !visible || locked;
        input.required = visible && !locked;
        if (visible && value !== undefined) {
            input.value = value;
        }
        if (!visible) {
            input.value = "";
        }
    };

    const initializeLocationFields = async (container) => {
        const countrySelect = container.querySelector("[data-location-country]");
        const regionSelect = container.querySelector("[data-location-region]");
        const citySelect = container.querySelector("[data-location-city]");
        const regionManual = container.querySelector("[data-location-region-manual]");
        const cityManual = container.querySelector("[data-location-city-manual]");
        const status = container.querySelector("[data-location-status]");
        if (!countrySelect || !regionSelect || !citySelect || !regionManual || !cityManual) {
            return;
        }

        const locked = countrySelect.disabled;
        const locationRequired = container.dataset.locationRequired === "true";
        const selectedCountry = container.dataset.selectedCountry || "";
        const selectedRegion = container.dataset.selectedRegion || "";
        const selectedCity = container.dataset.selectedCity || "";
        const apiBase = (container.dataset.locationApiBase || "/api/locations").replace(/\/$/, "");
        let requestVersion = 0;

        const setStatus = (message = "") => {
            if (status) {
                status.textContent = message;
            }
        };

        const setCityManualState = (value = "") => {
            const isManual = citySelect.value === OTHER_VALUE;
            setManualInput(cityManual, isManual, value, locked);
        };

        const loadCities = async (regionId, preferredCity = "") => {
            const version = ++requestVersion;
            const countryCode = countrySelect.value;
            citySelect.disabled = true;
            setManualInput(cityManual, false, "", locked);
            replaceOptions(citySelect, "Loading cities...", [], "id");
            try {
                const cities = await getItems(
                    `${apiBase}/cities?country_code=${encodeURIComponent(countryCode)}&region_id=${encodeURIComponent(regionId)}`
                );
                if (version !== requestVersion) {
                    return;
                }
                replaceOptions(
                    citySelect,
                    locationRequired ? "Select city/locality" : "Not set",
                    cities,
                    "id",
                    true
                );
                const matchedValue = findValueByLabel(citySelect, preferredCity);
                if (matchedValue) {
                    citySelect.value = matchedValue;
                } else if (preferredCity || cities.length === 0) {
                    citySelect.value = OTHER_VALUE;
                    setCityManualState(preferredCity);
                }
                citySelect.disabled = locked;
            } catch (error) {
                replaceOptions(citySelect, "Unable to load cities", [], "id", true);
                citySelect.disabled = locked;
                setStatus(error.message);
            }
        };

        const handleRegionChange = async (preferredCity = "") => {
            const selectedRegionId = regionSelect.value;
            setManualInput(regionManual, selectedRegionId === OTHER_VALUE, undefined, locked);
            if (!selectedRegionId) {
                requestVersion += 1;
                replaceOptions(citySelect, "Select region first", [], "id");
                citySelect.disabled = true;
                setManualInput(cityManual, false, "", locked);
                return;
            }
            if (selectedRegionId === OTHER_VALUE) {
                requestVersion += 1;
                replaceOptions(
                    citySelect,
                    locationRequired ? "Enter a city/locality manually" : "Not set",
                    [],
                    "id",
                    true
                );
                citySelect.value = preferredCity || locationRequired ? OTHER_VALUE : "";
                citySelect.disabled = locked;
                setCityManualState(preferredCity);
                return;
            }
            await loadCities(selectedRegionId, preferredCity);
        };

        const loadRegions = async (preferredRegion = "", preferredCity = "") => {
            const countryCode = countrySelect.value;
            const version = ++requestVersion;
            regionSelect.disabled = true;
            citySelect.disabled = true;
            setManualInput(regionManual, false, "", locked);
            setManualInput(cityManual, false, "", locked);
            if (!countryCode) {
                replaceOptions(regionSelect, "Select country first", [], "id");
                replaceOptions(citySelect, "Select region first", [], "id");
                return;
            }

            replaceOptions(regionSelect, "Loading regions...", [], "id");
            try {
                const regions = await getItems(
                    `${apiBase}/regions?country_code=${encodeURIComponent(countryCode)}`
                );
                if (version !== requestVersion) {
                    return;
                }
                replaceOptions(
                    regionSelect,
                    locationRequired ? "Select region/state/province" : "Not set",
                    regions,
                    "id",
                    true
                );
                const matchedValue = findValueByLabel(regionSelect, preferredRegion);
                if (matchedValue) {
                    regionSelect.value = matchedValue;
                } else if (preferredRegion || regions.length === 0) {
                    regionSelect.value = OTHER_VALUE;
                    setManualInput(regionManual, true, preferredRegion, locked);
                }
                regionSelect.disabled = locked;
                await handleRegionChange(preferredCity);
            } catch (error) {
                replaceOptions(regionSelect, "Unable to load regions", [], "id", true);
                regionSelect.disabled = locked;
                setStatus(error.message);
            }
        };

        countrySelect.disabled = true;
        try {
            const countries = await getItems(`${apiBase}/countries`);
            replaceOptions(
                countrySelect,
                locationRequired ? "Select country" : "Not set",
                countries,
                "code"
            );
            countrySelect.value = selectedCountry;
            countrySelect.disabled = locked;
            await loadRegions(selectedRegion, selectedCity);
        } catch (error) {
            replaceOptions(countrySelect, "Unable to load countries", [], "code");
            countrySelect.disabled = locked;
            setStatus(error.message);
        }

        countrySelect.addEventListener("change", () => {
            setStatus();
            loadRegions();
        });
        regionSelect.addEventListener("change", () => {
            setStatus();
            handleRegionChange();
        });
        citySelect.addEventListener("change", () => {
            setStatus();
            setCityManualState();
        });
        container.dataset.locationReady = "true";
        container.dispatchEvent(new CustomEvent("tis:location-ready", { bubbles: true }));
    };

    document.querySelectorAll("[data-location-fields]").forEach((container) => {
        initializeLocationFields(container);
    });
})();
