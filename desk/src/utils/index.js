import _dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import updateLocale from "dayjs/plugin/updateLocale";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";

_dayjs.extend(relativeTime);
_dayjs.extend(updateLocale);
_dayjs.extend(utc);
_dayjs.extend(timezone);

_dayjs.longFormating = (s) => {
	if (s === "now" || s === "now ago") {
		return "just now";
	}
	return s;
};

_dayjs.shortFormating = (s, ago = false) => {
	if (s === "now" || s === "now ago") {
		return "now";
	}

	const prefix = s.split(" ")[0];
	const posfix = s.split(" ")[1];
	const isPast = s.includes("ago");
	let newPostfix = "";
	switch (posfix) {
		case "minute":
			newPostfix = "m";
			break;
		case "minutes":
			newPostfix = "m";
			break;
		case "hour":
			newPostfix = "h";
			break;
		case "hours":
			newPostfix = "h";
			break;
		case "day":
			newPostfix = "d";
			break;
		case "days":
			newPostfix = "d";
			break;
		case "month":
			newPostfix = "M";
			break;
		case "months":
			newPostfix = "M";
			break;
		case "year":
			newPostfix = "Y";
			break;
		case "years":
			newPostfix = "Y";
			break;
	}
	return `${prefix}${newPostfix}${isPast ? (ago ? " ago" : "") : ""}`;
};

export function remove_script_and_style(txt) {
	const evil_tags = ["script", "noscript", "title", "meta", "base", "head"];
	const regex = new RegExp(
		evil_tags.map((tag) => `<${tag}>.*<\\/${tag}>`).join("|"),
		"s"
	);
	if (!regex.test(txt)) {
		// no evil tags found, skip the DOM method entirely!
		return txt;
	}

	var div = document.createElement("div");
	div.innerHTML = txt;
	var found = false;
	evil_tags.forEach(function (e) {
		var elements = div.getElementsByTagName(e);
		i = elements.length;
		while (i--) {
			found = true;
			elements[i].parentNode.removeChild(elements[i]);
		}
	});

	// remove links with rel="stylesheet"
	var elements = div.getElementsByTagName("link");
	var i = elements.length;
	while (i--) {
		if (elements[i].getAttribute("rel") == "stylesheet") {
			found = true;
			elements[i].parentNode.removeChild(elements[i]);
		}
	}
	if (found) {
		return div.innerHTML;
	} else {
		// don't disturb
		return txt;
	}
}

export let dayjs = _dayjs;
