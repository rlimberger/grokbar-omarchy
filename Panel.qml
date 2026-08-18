import QtQuick
import qs.Commons
import qs.Ui

// Usage popup. BarWidget.qml owns the bar slot and scan state.
// Grok card mirrors grok.com Settings → Usage (weekly pool + products).
// Cursor card (X-login only) shows two monthly pools + a shared reset.
Panel {
  id: root
  moduleName: "rlimberger.grokbar-omarchy"
  ipcTarget: "rlimberger.grokbar-omarchy"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  // Theme aliases only — no hardcoded greens/reds.
  // Under pace: accent; over pace: urgent.
  // Pace marker uses full accent so it reads apart from faint day ticks.
  readonly property color underPaceColor: Color.accent
  readonly property color overPaceColor: Color.urgent
  readonly property color paceMarkerColor: Color.accent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color surface: Color.popups.background
  readonly property color track: Style.selectedFillFor(foreground, Color.accent)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property real rawPrimaryPercent: hostWidget ? Number(hostWidget.primaryPercent) : -1
  readonly property string resetAt: hostWidget ? String(hostWidget.resetAt || "") : ""
  readonly property string periodStart: hostWidget ? String(hostWidget.periodStart || "") : ""
  readonly property string tierLabel: hostWidget ? String(hostWidget.tierLabel || "") : ""
  // Written by BarWidget.injectPanel after each scan. Do not read these
  // back through hostWidget — that binding stayed empty in the running shell.
  property string grokLoginEmail: ""
  readonly property string usageStatusText: hostWidget ? String(hostWidget.usageStatusText || "") : ""
  readonly property string authHelpText: hostWidget ? String(hostWidget.authHelpText || "") : ""
  readonly property var categories: hostWidget && hostWidget.categories ? hostWidget.categories : []
  readonly property double nowMs: hostWidget ? Number(hostWidget.nowMs) : Date.now()

  readonly property bool grokHasData: rawPrimaryPercent >= 0
  readonly property real cursorAutoPercent: hostWidget ? Number(hostWidget.cursorAutoPercent) : -1
  readonly property real cursorApiPercent: hostWidget ? Number(hostWidget.cursorApiPercent) : -1
  readonly property string cursorResetAt: hostWidget ? String(hostWidget.cursorResetAt || "") : ""
  readonly property string cursorPeriodStart: hostWidget ? String(hostWidget.cursorPeriodStart || "") : ""
  readonly property string cursorTierLabel: hostWidget ? String(hostWidget.cursorTierLabel || "") : ""
  property string cursorLoginEmail: ""
  readonly property string cursorUsageStatusText: hostWidget ? String(hostWidget.cursorUsageStatusText || "") : ""
  readonly property string cursorAuthHelpText: hostWidget ? String(hostWidget.cursorAuthHelpText || "") : ""
  readonly property bool cursorHasData: cursorAutoPercent >= 0 || cursorApiPercent >= 0

  // TEMP QA hook: force over-pace styling (leave false in production).
  readonly property bool simulateOverPace: false

  // Linear expected usage by now: elapsed / period length (0–1).
  readonly property real expectedPace: {
    if (hostWidget && typeof hostWidget.expectedPace === "number"
        && isFinite(hostWidget.expectedPace) && hostWidget.expectedPace >= 0)
      return Math.max(0, Math.min(1, Number(hostWidget.expectedPace)))
    var start = root.parseTimeMs(periodStart)
    var end = root.parseTimeMs(resetAt)
    if (!(end > 0)) return -1
    if (!(start > 0) || !(start < end))
      start = end - 7 * 24 * 3600 * 1000
    var frac = (nowMs - start) / (end - start)
    if (!isFinite(frac)) return -1
    return Math.max(0, Math.min(1, frac))
  }

  // Displayed usage: when simulating, push past the pace marker (~+15pp, min past pace).
  readonly property real primaryPercent: {
    var raw = rawPrimaryPercent
    if (!root.simulateOverPace || !(raw >= 0) || !(expectedPace >= 0))
      return raw
    var bumped = Math.max(raw, expectedPace + 0.15)
    return Math.max(0, Math.min(1, bumped))
  }

  readonly property bool overPace: expectedPace >= 0 && primaryPercent >= 0
    && primaryPercent > expectedPace + 0.0001
  readonly property color usageFillColor: overPace ? overPaceColor : underPaceColor

  // Non-zero product slices only (matches official Usage card).
  readonly property var productLimits: {
    var out = []
    var cats = root.categories
    if (!cats || !cats.length) return out
    for (var i = 0; i < cats.length; i++) {
      var c = cats[i]
      if (!c) continue
      var pct = Number(c.percent)
      if (!isFinite(pct) || pct <= 0) continue
      out.push({
        title: String(c.title || "Product"),
        type: Number(c.type),
        percent: pct
      })
    }
    return out
  }

  // Hero title: subscription type only, e.g. "SuperGrok Heavy"
  readonly property string weeklyTitle: {
    if (tierLabel !== "") return tierLabel
    return "Grok"
  }

  // Status only — email is shown as a normal-case line (PanelHero.meta is uppercase).
  readonly property string heroMeta: {
    if (usageStatusText !== "") return usageStatusText
    return ""
  }

  // "23% of weekly limit used"
  readonly property string usedLabel: primaryPercent >= 0
    ? Math.round(primaryPercent * 100) + "% of weekly limit used"
    : ""

  // "Resets Aug 13, 9AM" (short month, no year)
  readonly property string resetsLabel: root.formatResetsLabel(resetAt)

  readonly property bool alarming: primaryPercent >= 0.9 || overPace

  readonly property real cursorExpectedPace: {
    if (hostWidget && typeof hostWidget.cursorExpectedPace === "number"
        && isFinite(hostWidget.cursorExpectedPace) && hostWidget.cursorExpectedPace >= 0)
      return Math.max(0, Math.min(1, Number(hostWidget.cursorExpectedPace)))
    var start = root.parseTimeMs(cursorPeriodStart)
    var end = root.parseTimeMs(cursorResetAt)
    if (!(end > 0)) return -1
    if (!(start > 0) || !(start < end))
      start = end - 30 * 24 * 3600 * 1000
    var frac = (nowMs - start) / (end - start)
    if (!isFinite(frac)) return -1
    return Math.max(0, Math.min(1, frac))
  }

  readonly property real cursorAutoDisplay: {
    var raw = cursorAutoPercent
    if (!root.simulateOverPace || !(raw >= 0) || !(cursorExpectedPace >= 0))
      return raw
    return Math.max(0, Math.min(1, Math.max(raw, cursorExpectedPace + 0.15)))
  }
  readonly property real cursorApiDisplay: {
    var raw = cursorApiPercent
    if (!root.simulateOverPace || !(raw >= 0) || !(cursorExpectedPace >= 0))
      return raw
    return Math.max(0, Math.min(1, Math.max(raw, cursorExpectedPace + 0.15)))
  }
  readonly property bool cursorAutoOverPace: cursorExpectedPace >= 0 && cursorAutoDisplay >= 0
    && cursorAutoDisplay > cursorExpectedPace + 0.0001
  readonly property bool cursorApiOverPace: cursorExpectedPace >= 0 && cursorApiDisplay >= 0
    && cursorApiDisplay > cursorExpectedPace + 0.0001

  readonly property var cursorPools: {
    var out = []
    if (cursorAutoDisplay >= 0)
      out.push({ title: "Cursor Models", percent: cursorAutoDisplay, overPace: cursorAutoOverPace })
    if (cursorApiDisplay >= 0)
      out.push({ title: "Other Models", percent: cursorApiDisplay, overPace: cursorApiOverPace })
    return out
  }

  readonly property string cursorTitle: cursorTierLabel !== "" ? cursorTierLabel : "Cursor"
  readonly property string cursorHeroMeta: {
    if (cursorUsageStatusText !== "") return cursorUsageStatusText
    return ""
  }
  readonly property string cursorResetsLabel: root.formatResetsLabel(cursorResetAt)
  readonly property url cursorIconSource: colorLuminance(surface) >= 0.5
    ? Qt.resolvedUrl("assets/cursor-light.svg")
    : Qt.resolvedUrl("assets/cursor.svg")

  // Segment shades of the pace-aware fill color (accent under, urgent over).
  readonly property var segmentPalette: {
    var base = root.usageFillColor
    return [
      base,
      Qt.rgba(base.r, base.g, base.b, 0.72),
      Qt.rgba(base.r, base.g, base.b, 0.50),
      Qt.rgba(base.r, base.g, base.b, 0.86),
      Qt.rgba(base.r, base.g, base.b, 0.60)
    ]
  }

  readonly property url iconSource: colorLuminance(surface) >= 0.5
    ? Qt.resolvedUrl("assets/grok-light.svg")
    : Qt.resolvedUrl("assets/grok.svg")

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

  function parseTimeMs(value) {
    var text = String(value || "").trim()
    if (text === "") return NaN
    var t = new Date(text).getTime()
    return isFinite(t) ? t : NaN
  }

  function colorChannelLuminance(value) {
    var channel = Number(value)
    if (!isFinite(channel)) return 0
    return channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)
  }

  function colorLuminance(color) {
    return 0.2126 * colorChannelLuminance(color.r)
      + 0.7152 * colorChannelLuminance(color.g)
      + 0.0722 * colorChannelLuminance(color.b)
  }

  function parseResetWhen(iso) {
    var text = String(iso || "").trim()
    if (text === "") return null
    var when = new Date(text)
    var t = when.getTime()
    if (isFinite(t)) return when
    var m = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/)
    if (!m) return null
    t = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]),
                 Number(m[4]), Number(m[5]), Number(m[6]))
    when = new Date(t)
    return isFinite(t) ? when : null
  }

  // "Resets Aug 13, 9AM" (local time; minutes only when not :00).
  function formatResetsLabel(iso) {
    var when = root.parseResetWhen(iso)
    if (!when) return ""
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    var h = when.getHours()
    var min = when.getMinutes()
    var ampm = h >= 12 ? "PM" : "AM"
    var h12 = h % 12
    if (h12 === 0) h12 = 12
    var timePart = min > 0
      ? (h12 + ":" + (min < 10 ? "0" : "") + min + ampm)
      : (h12 + ampm)
    return "Resets " + months[when.getMonth()] + " " + when.getDate()
      + ", " + timePart
  }

  function segmentColor(index) {
    var palette = root.segmentPalette
    if (!palette || !palette.length) return root.usageFillColor
    return palette[index % palette.length]
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  function open() {
    root.controller.show()
    Qt.callLater(function() {
      if (root.opened) setCenterHoverRevealSuppressed(true)
    })
  }

  function openFromHotkey() { open() }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) close()
    else open()
  }

  function refresh() {
    if (hostWidget && typeof hostWidget.refresh === "function")
      hostWidget.refresh()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(520))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      onActivateRequested: root.refresh()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) { if (t === "r" || t === "R") root.refresh() }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(12)

        // Grok card. Hidden when there is nothing to say about Grok.
        Column {
          id: grokCard
          visible: root.grokHasData || root.usageStatusText !== ""
          width: parent.width
          spacing: Style.space(12)

        PanelHero {
          width: parent.width
          title: root.weeklyTitle
          meta: root.heroMeta
          detail: root.grokLoginEmail
          foreground: root.foreground
          fontFamily: root.fontFamily

          iconComponent: Component {
            Image {
              source: root.iconSource
              width: Style.font.display
              height: Style.font.display
              sourceSize.width: Style.font.display * 2
              sourceSize.height: Style.font.display * 2
              fillMode: Image.PreserveAspectFit
            }
          }
        }

        BorderSurface {
          visible: root.usageStatusText !== ""
          width: parent.width
          implicitHeight: statusText.implicitHeight + Style.spacing.xl * 2
          color: Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.10)
          borderSpec: Border.flat(Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.35), 1)
          radius: Style.cornerRadius

          Text {
            id: statusText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(12)
            anchors.rightMargin: Style.space(12)
            text: root.authHelpText !== "" ? root.authHelpText : root.usageStatusText
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }

        PanelSeparator {
          visible: usageSection.visible
          foreground: root.foreground
        }

        // Usage body (no section header — title lives in the hero).
        Column {
          id: usageSection
          visible: root.primaryPercent >= 0
          width: parent.width
          spacing: Style.space(10)

          // "23% used" ……………… "Resets August 13, 2026 at 9:46 PM"
          Item {
            width: parent.width
            implicitHeight: Math.max(usedText.implicitHeight, resetsText.implicitHeight)

            Text {
              id: usedText
              text: root.usedLabel
              color: root.alarming ? root.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Text {
              id: resetsText
              visible: text !== ""
              text: root.resetsLabel
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideLeft
              horizontalAlignment: Text.AlignRight
              anchors.right: parent.right
              anchors.left: usedText.right
              anchors.leftMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          // Segmented weekly bar (Chat | Grok Build | …) + day ticks + pace marker.
          SegmentedMeter {
            width: parent.width
            visible: root.productLimits.length > 0 || root.primaryPercent >= 0
            segments: root.productLimits
            totalPercent: root.primaryPercent
            expectedPace: root.expectedPace
            overPace: root.overPace
            fillColor: root.usageFillColor
            paceMarkerColor: root.paceMarkerColor
          }

          // "• Chat 12%  • Grok Build 11%"
          Flow {
            id: legend
            visible: root.productLimits.length > 0
            width: parent.width
            spacing: Style.space(12)

            Repeater {
              model: root.productLimits

              Row {
                required property var modelData
                required property int index
                spacing: Style.space(5)

                Rectangle {
                  width: Style.space(6)
                  height: Style.space(6)
                  radius: width / 2
                  anchors.verticalCenter: parent.verticalCenter
                  color: root.segmentColor(index)
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: (modelData.title || "Product") + " "
                    + Math.round(Number(modelData.percent) * 100) + "%"
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  renderType: Text.NativeRendering
                }
              }
            }
          }
        }
        }

        PanelSeparator {
          visible: grokCard.visible && cursorCard.visible
          foreground: root.foreground
        }

        Column {
          id: cursorCard
          visible: root.cursorHasData || root.cursorUsageStatusText !== ""
          width: parent.width
          spacing: Style.space(12)

          PanelHero {
            width: parent.width
            title: root.cursorTitle
            meta: root.cursorHeroMeta
            detail: root.cursorLoginEmail
            foreground: root.foreground
            fontFamily: root.fontFamily

            iconComponent: Component {
              Image {
                source: root.cursorIconSource
                width: Style.font.display
                height: Style.font.display
                sourceSize.width: Style.font.display * 2
                sourceSize.height: Style.font.display * 2
                fillMode: Image.PreserveAspectFit
              }
            }
          }

          BorderSurface {
            visible: root.cursorUsageStatusText !== ""
            width: parent.width
            implicitHeight: cursorStatusText.implicitHeight + Style.spacing.xl * 2
            color: Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.10)
            borderSpec: Border.flat(Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.35), 1)
            radius: Style.cornerRadius

            Text {
              id: cursorStatusText
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.space(12)
              anchors.rightMargin: Style.space(12)
              text: root.cursorAuthHelpText !== "" ? root.cursorAuthHelpText : root.cursorUsageStatusText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          Column {
            visible: root.cursorHasData
            width: parent.width
            spacing: Style.space(10)

            Repeater {
              model: root.cursorPools

              Column {
                required property var modelData
                required property int index
                width: cursorCard.width
                spacing: Style.space(6)

                Item {
                  width: parent.width
                  implicitHeight: Math.max(poolUsedText.implicitHeight, poolResetText.implicitHeight)

                  Text {
                    id: poolUsedText
                    width: parent.width
                      - (poolResetText.visible ? poolResetText.implicitWidth + Style.space(10) : 0)
                    text: (modelData.title || "Pool") + " · "
                      + Math.round(Number(modelData.percent) * 100) + "% of monthly limit used"
                    color: (modelData.overPace || Number(modelData.percent) >= 0.9)
                      ? root.urgent : root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                  }

                  Text {
                    id: poolResetText
                    visible: index === 0 && root.cursorResetsLabel !== ""
                    text: root.cursorResetsLabel
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideLeft
                    horizontalAlignment: Text.AlignRight
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                  }
                }

                SegmentedMeter {
                  width: parent.width
                  segments: []
                  totalPercent: Number(modelData.percent)
                  expectedPace: root.cursorExpectedPace
                  overPace: modelData.overPace === true
                  fillColor: modelData.overPace ? root.overPaceColor : root.underPaceColor
                  paceMarkerColor: root.paceMarkerColor
                  dayCount: 0
                }
              }
            }
          }
        }
      }
    }
  }

  // Full-width track with product slices left-to-right (pool fractions).
  // Day ticks + expected-pace marker (elapsed / period).
  // Fill uses Color.accent under pace, Color.urgent over pace.
  component SegmentedMeter: Item {
    id: meter
    property var segments: []
    property real totalPercent: -1
    property real expectedPace: -1
    property bool overPace: false
    property color fillColor: root.usageFillColor
    property color paceMarkerColor: root.paceMarkerColor
    // SuperGrok weekly pool = 7 calendar days.
    property int dayCount: 7
    property real thickness: Math.max(Style.space(6), Math.round(Style.spacing.controlHeight * 0.18))

    implicitHeight: thickness

    // dayCount < 2 → no ticks (monthly Cursor pools use dayCount: 0).
    readonly property int dayMarkerCount: dayCount >= 2 ? dayCount - 1 : 0

    readonly property real usedFraction: {
      if (meter.totalPercent >= 0) return root.clamp(meter.totalPercent, 0, 1)
      var sum = 0
      var segs = meter.segments || []
      for (var i = 0; i < segs.length; i++) {
        var p = Number(segs[i] && segs[i].percent)
        if (isFinite(p) && p > 0) sum += p
      }
      return root.clamp(sum, 0, 1)
    }

    readonly property real paceFraction: {
      var p = Number(meter.expectedPace)
      if (!isFinite(p) || p < 0) return -1
      return root.clamp(p, 0, 1)
    }

    // Day ticks: fainter on empty track, inverted/higher-contrast over used fill.
    readonly property color dayMarkerOnTrack: Qt.rgba(
      root.foreground.r, root.foreground.g, root.foreground.b, 0.28)
    readonly property color dayMarkerOnFill: Qt.rgba(
      root.track.r, root.track.g, root.track.b, 0.72)

    Rectangle {
      id: meterTrack
      anchors.fill: parent
      radius: height / 2
      color: root.track
      clip: true

      Row {
        id: fillRow
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        height: parent.height
        width: parent.width * meter.usedFraction
        z: 1

        Repeater {
          model: meter.segments

          Rectangle {
            required property var modelData
            required property int index
            readonly property real pct: {
              var p = Number(modelData && modelData.percent)
              return isFinite(p) && p > 0 ? p : 0
            }
            width: {
              var used = meter.usedFraction
              if (!(used > 0) || !(pct > 0)) return 0
              return fillRow.width * (pct / used)
            }
            height: parent.height
            color: root.segmentColor(index)
          }
        }

        // Solid fill when we have total % but no product slices yet.
        Rectangle {
          visible: (!meter.segments || meter.segments.length === 0) && meter.usedFraction > 0
          width: fillRow.width
          height: parent.height
          color: meter.fillColor
        }
      }

      // Day boundary ticks at 1/N … (N-1)/N of the full week width.
      Item {
        id: dayMarkers
        anchors.fill: parent
        z: 2

        Repeater {
          model: meter.dayMarkerCount

          Rectangle {
            required property int index
            readonly property real dayFraction: (index + 1) / meter.dayCount
            readonly property bool overUsed: dayFraction <= meter.usedFraction + 0.0001

            width: Math.max(1, Math.round(Style.space(1)))
            height: Math.max(2, Math.round(parent.height * 0.78))
            radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            x: Math.round(parent.width * dayFraction - width / 2)
            color: overUsed ? meter.dayMarkerOnFill : meter.dayMarkerOnTrack
          }
        }
      }

      // Expected-pace marker: where linear usage "should" be right now.
      // Stronger than day ticks (solid accent, slightly wider, full height).
      Rectangle {
        id: paceMarker
        visible: meter.paceFraction >= 0
        z: 3
        width: Math.max(2, Math.round(Style.space(2)))
        height: parent.height
        radius: width / 2
        anchors.verticalCenter: parent.verticalCenter
        x: Math.round(parent.width * meter.paceFraction - width / 2)
        color: meter.paceMarkerColor
      }
    }
  }
}
