// The phone's view layer: Ionic's web components (@ionic/core, MIT; THIRD_PARTY_NOTICES.md), forced
// into iOS mode for the native look on every browser. Only the components the phone uses are
// registered, so the bundle carries nothing else. Data, drawing and tests do not depend on it.

import "@ionic/core/css/core.css";
import "@ionic/core/css/normalize.css";
import "@ionic/core/css/structure.css";
import "@ionic/core/css/typography.css";
import "@ionic/core/css/padding.css";
import "@ionic/core/css/display.css";
import "@ionic/core/css/palettes/dark.system.css";
import "./theme.css"; // ours, after Ionic's, so our variables win
import { initialize } from "@ionic/core/components";
import { defineCustomElement as app } from "@ionic/core/components/ion-app.js";
import { defineCustomElement as buttons } from "@ionic/core/components/ion-buttons.js";
import { defineCustomElement as chip } from "@ionic/core/components/ion-chip.js";
import { defineCustomElement as content } from "@ionic/core/components/ion-content.js";
import { defineCustomElement as footer } from "@ionic/core/components/ion-footer.js";
import { defineCustomElement as header } from "@ionic/core/components/ion-header.js";
import { defineCustomElement as item } from "@ionic/core/components/ion-item.js";
import { defineCustomElement as label } from "@ionic/core/components/ion-label.js";
import { defineCustomElement as list } from "@ionic/core/components/ion-list.js";
import { defineCustomElement as listHeader } from "@ionic/core/components/ion-list-header.js";
import { defineCustomElement as modal } from "@ionic/core/components/ion-modal.js";
import { defineCustomElement as note } from "@ionic/core/components/ion-note.js";
import { defineCustomElement as segment } from "@ionic/core/components/ion-segment.js";
import { defineCustomElement as segmentButton } from "@ionic/core/components/ion-segment-button.js";
import { defineCustomElement as tab } from "@ionic/core/components/ion-tab.js";
import { defineCustomElement as tabBar } from "@ionic/core/components/ion-tab-bar.js";
import { defineCustomElement as tabButton } from "@ionic/core/components/ion-tab-button.js";
import { defineCustomElement as tabs } from "@ionic/core/components/ion-tabs.js";
import { defineCustomElement as title } from "@ionic/core/components/ion-title.js";
import { defineCustomElement as toolbar } from "@ionic/core/components/ion-toolbar.js";

initialize({ mode: "ios" });
for (const define of [app, buttons, chip, content, footer, header, item, label, list, listHeader, modal, note, segment, segmentButton, tab, tabBar, tabButton, tabs, title, toolbar]) {
  define();
}
