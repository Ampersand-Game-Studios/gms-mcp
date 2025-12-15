// Inherit
event_inherited();
// Defaults (actual text assigned at instantiation)
text_string = ""; text_string_prev = text_string + "a";
font = fnt_default_42; alignment_h = fa_center; alignment_v = fa_middle;
shadow_enable = true; shadow_x = -3; shadow_y = 3; shadow_c = c_black; shadow_alpha = 1;
text_ui_set_width_height_pre_scale(); width = width_pre_scale * image_xscale; height = height_pre_scale * image_yscale;
state_script[UIState.create][UIStateStage.main] = ui_gameover_create_main;
