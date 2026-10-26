//! List-owned typing shares the ordinary Liked Songs field's temporary query.

use egui::{Event, Id, Key, Modifiers};

use crate::{app::App, model::Page, theme::Palette};

pub(super) fn query(ctx: &egui::Context) -> String {
    ctx.data(|data| data.get_temp::<String>(Id::new("liked-filter")))
        .unwrap_or_default()
}

pub(super) fn set_query(ctx: &egui::Context, query: String) {
    ctx.data_mut(|data| {
        data.insert_temp(Id::new("liked-filter"), query);
        data.insert_temp(Id::new("liked-filter-focus"), true);
    });
}

fn plain(modifiers: Modifiers) -> bool {
    !modifiers.ctrl && !modifiers.command && !modifiers.mac_cmd && !modifiers.alt
}

/// Work on committed text, including IME input, rather than keyboard layouts.
fn edit(query: &mut String, events: &mut Vec<Event>, modifiers: Modifiers) -> bool {
    if !plain(modifiers) {
        return false;
    }
    let before = query.clone();
    let mut took_text = false;
    let mut took_ime = false;
    let mut took_space = !query.is_empty();
    events.retain(|event| match event {
        Event::Text(text) | Event::Ime(egui::ImeEvent::Commit(text))
            if !text.chars().any(char::is_control)
                && (!query.is_empty() || text.starts_with(char::is_alphanumeric)) =>
        {
            took_ime |= matches!(event, Event::Ime(_));
            query.push_str(text);
            took_text = true;
            took_space |= text.contains(' ');
            false
        }
        Event::Key {
            key,
            pressed: true,
            modifiers,
            ..
        } if plain(*modifiers) && !query.is_empty() => match key {
            Key::Backspace => {
                query.pop();
                false
            }
            Key::Escape => {
                query.clear();
                false
            }
            _ => true,
        },
        _ => true,
    });
    // The physical key often precedes Text. Remove it after processing text so
    // a typed m, slash or question mark cannot also activate a global shortcut.
    events.retain(|event| {
        !matches!(event, Event::Key { key, modifiers, .. }
            if plain(*modifiers)
                && ((took_text
                    && !matches!(key, Key::ArrowUp | Key::ArrowDown | Key::ArrowLeft | Key::ArrowRight)
                    && key.symbol_or_name().chars().count() == 1)
                    || (took_space && *key == Key::Space)
                    || (took_ime && *key == Key::Enter)))
    });
    *query != before
}

pub(super) fn handle(app: &App, ctx: &egui::Context) {
    if app.page() != &Page::LikedSongs
        || ctx.text_edit_focused()
        || app.dialog.is_some()
        || app.show_devices
        || app.show_update
        || app.lyrics_fullscreen.is_some()
        || egui::Popup::is_any_open(ctx)
    {
        return;
    }
    // Allow a native input method without moving focus into a TextEdit.
    let rect = egui::Rect::from_min_size(ctx.content_rect().min, egui::vec2(1.0, 24.0));
    ctx.output_mut(|output| {
        output.ime = Some(egui::output::IMEOutput {
            purpose: egui::IMEPurpose::Normal,
            rect,
            cursor_rect: rect,
            should_interrupt_composition: false,
        });
    });
    let mut value = query(ctx);
    if ctx.input_mut(|input| edit(&mut value, &mut input.events, input.modifiers)) {
        set_query(ctx, value);
    }
}

/// This is laid out below the toolbar, before the page's ScrollArea.
pub(super) fn indicator(ui: &mut egui::Ui, palette: &Palette) {
    let value = query(ui.ctx());
    if value.is_empty() {
        return;
    }
    egui::Frame::new()
        .stroke(egui::Stroke::new(1.5, egui::Color32::from_rgb(29, 185, 84)))
        .corner_radius(5)
        .inner_margin(6)
        .show(ui, |ui| {
            ui.horizontal(|ui| {
                let width = (ui.available_width() - 60.0).max(0.0);
                ui.add_sized(
                    [width, 20.0],
                    egui::Label::new(
                        egui::RichText::new(format!("Mod search: {value}")).color(palette.text),
                    )
                    .truncate(),
                );
                let clear = ui
                    .button("Clear")
                    .on_hover_text("Clear Liked Songs filter (Escape)");
                ui.ctx().accesskit_node_builder(clear.id, |node| {
                    node.set_label("Clear Liked Songs filter");
                });
                if clear.clicked() {
                    set_query(ui.ctx(), String::new());
                }
            });
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(key: Key, modifiers: Modifiers) -> Event {
        Event::Key {
            key,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers,
        }
    }

    #[test]
    fn committed_text_precedes_shortcuts_and_keeps_unicode() {
        let mut query = String::new();
        for (physical, text) in [
            (Key::M, "M"),
            (Key::Space, " "),
            (Key::Slash, "/"),
            (Key::Questionmark, "?"),
            (Key::A, "é東京"),
        ] {
            let mut events = vec![key(physical, Modifiers::NONE), Event::Text(text.into())];
            assert!(edit(&mut query, &mut events, Modifiers::NONE));
            assert!(events.is_empty());
        }
        assert_eq!(query, "M /?é東京");
        edit(
            &mut query,
            &mut vec![key(Key::Backspace, Modifiers::NONE)],
            Modifiers::NONE,
        );
        assert_eq!(query, "M /?é東");
        edit(
            &mut query,
            &mut vec![key(Key::Escape, Modifiers::NONE)],
            Modifiers::NONE,
        );
        assert!(query.is_empty());
    }

    #[test]
    fn empty_space_punctuation_and_modified_shortcuts_are_preserved() {
        for text in [" ", "/", "?"] {
            let mut events = vec![Event::Text(text.into())];
            assert!(!edit(&mut String::new(), &mut events, Modifiers::NONE));
            assert_eq!(events.len(), 1);
        }
        let mut query = "song".to_string();
        let mut events = vec![key(Key::A, Modifiers::COMMAND), Event::Text("a".into())];
        assert!(!edit(&mut query, &mut events, Modifiers::COMMAND));
        assert_eq!(query, "song");
        assert_eq!(events.len(), 2);
        assert!(edit(
            &mut String::new(),
            &mut vec![Event::Text("2".into())],
            Modifiers::NONE
        ));
    }

    #[test]
    fn ime_commit_filters_without_consuming_arrow_navigation() {
        let mut query = String::new();
        let mut events = vec![
            Event::Ime(egui::ImeEvent::Commit("東京".into())),
            key(Key::ArrowDown, Modifiers::NONE),
        ];
        assert!(edit(&mut query, &mut events, Modifiers::NONE));
        assert_eq!(query, "東京");
        assert_eq!(events.len(), 1);
        assert!(matches!(
            events[0],
            Event::Key {
                key: Key::ArrowDown,
                ..
            }
        ));
        let mut commit = vec![
            key(Key::Enter, Modifiers::NONE),
            Event::Ime(egui::ImeEvent::Commit("語".into())),
        ];
        assert!(edit(&mut query, &mut commit, Modifiers::NONE));
        assert!(commit.is_empty(), "IME confirmation must not play a row");
    }
}
