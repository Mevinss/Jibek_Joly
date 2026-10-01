const root = new URL('./locales/', import.meta.url);
const dictionaries = await Promise.all(['ru', 'kk'].map(async language => {
  const response = await fetch(new URL(`${language}.json`, root));
  if (!response.ok) throw new Error(`Locale ${language}: HTTP ${response.status}`);
  return response.json();
}));
export const bi = key => dictionaries.map(d => d[key] ?? key);
export const tr = (key, language = 0) => dictionaries[language ? 1 : 0][key] ?? dictionaries[0][key] ?? key;
