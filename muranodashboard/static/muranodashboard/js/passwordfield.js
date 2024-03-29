/*    Copyright (c) 2013 Mirantis, Inc.

    Licensed under the Apache License, Version 2.0 (the "License"); you may
    not use this file except in compliance with the License. You may obtain
    a copy of the License at

         http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
    License for the specific language governing permissions and limitations
    under the License.
*/
$(function() {
    function main_check(div, parameter1, parameter2, text){
        var msg = "<span class='help-inline'>" + gettext(text) + '</span>'
        var error_node = div.find("span.help-inline")
        var not_added;
        if (error_node.length) {
            not_added = false;
            error_node.text(text);
        } else {
            not_added = true;

        };
        if (parameter1 != parameter2 && not_added) {
            div.addClass("error");
            div.find("label").after(msg)
        } else if (parameter1 == parameter2) {
            div.removeClass("error");
            error_node.remove();
        }
    }

    function check_passwords_match(event) {
        var $this = $(event.target);
        var password = $this.closest(".form-field").prev().find("input").val();
        var confirm_password = $this.val();
        var div = $this.closest(".form-field");
        main_check(div, password,confirm_password, "Passwords do not match")
    }

    function check_strength_remove_err_if_matches(event){
        var $this = $(event.target);
        var password = $this.val();
        var div_confirm = $this.closest(".form-field").next();
        var confirm_password = div_confirm.find("input").val();
        var div = $this.closest(".form-field").next();
        if (confirm_password.length){
            main_check(div, password, confirm_password, "Passwords do not match");
        }
        var text = "Your password should have at least"
        var meet_requirements = true;
        if (password.length<7){
            text += " 7 characters";
            meet_requirements = false;
        }
        if (password.match(/[A-Z]+/) == null){
            text += " 1 capital letter";
            meet_requirements = false;
        }
        if (password.match(/[a-z]+/) == null) {
            text += " 1 non-capital letter";
            meet_requirements = false;
        }
        if (password.match(/[0-9]+/) == null){
            text += " 1 digit";
            meet_requirements = false;
        }

        if (password.match(/[!@#$%^&*()_+|\/.,~?><:{}]+/) == null) {
            text += " 1 specical character";
            meet_requirements = false;
        }
        var div = $this.closest(".form-field")
        main_check(div, meet_requirements, true, text);
    };

    $("input[id$='Password'][type='password']").change(check_strength_remove_err_if_matches);
    $("input[id*='assword-clone'][type='password']").change(check_passwords_match);

});
