// =============================================================================
//  PackageManifest.cpp
// =============================================================================
#include "PackageManifest.h"
#include <ArduinoJson.h>
#include <algorithm>

namespace PackageManifest {

std::vector<PackageInfo> read(Storage& sd) {
  std::vector<PackageInfo> out;
  fs::File f = sd.openRead(PATH);
  if (!f || f.isDirectory() || f.size() > 32 * 1024) return out;   // tope de RAM

  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, f);
  f.close();
  if (e || !doc.is<JsonObject>()) return out;

  for (JsonPair kv : doc.as<JsonObject>()) {
    PackageInfo p;
    p.name = kv.key().c_str();
    JsonObject o = kv.value().as<JsonObject>();
    p.version = o["version"] | "?";
    p.source = o["source"] | "?";
    p.files = o["files"].is<JsonArray>() ? o["files"].as<JsonArray>().size() : 0;
    out.push_back(p);
  }
  std::sort(out.begin(), out.end(), [](const PackageInfo& a, const PackageInfo& b) {
    return strcasecmp(a.name.c_str(), b.name.c_str()) < 0;
  });
  return out;
}

}  // namespace PackageManifest
