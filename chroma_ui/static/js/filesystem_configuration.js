
/* fvc: Filesystem Volume Chooser */

var fvc_instances = []

fvc_clear = function(element) {
  opts = fvc_instances[element.attr('id')]
  element = $('#' + element.attr('id'));

  var changed;
  if (opts.multi_select) {
    if(opts['selected_lun_ids'] && opts['selected_lun_ids'].length > 0) {
      changed = true;
    }
    opts['selected_lun_ids'] = []
    element.parents('.fvc_background').find('input').attr('checked', false);
  } else {
    if(opts['selected_lun_id'] != null) {
      changed = true;
    }
    opts['selected_lun_id'] = null
    element.parents('.fvc_background').find('.fvc_selected').html("Select storage...")
  }
  if (changed && opts.change) {
    opts.change();
  }
}

fvc_get_value = function(element) {
  opts = fvc_instances[element.attr('id')]
  //console.log(opts);
  if (opts.multi_select) {
    return opts.selected_lun_ids
  } else {
    return opts.selected_lun_id
  }
}

fvc_button = function(element, opts) {
  if (!opts) {
    opts = []
  }

  fvc_instances[element.attr('id')] = opts

  element.wrap("<div class='fvc_background'/>")
  element.hide()
  var background_div = element.parent('.fvc_background')

  element.wrap("<div class='fvc_header'/>");
  var header_div = element.parent('.fvc_header')

  element.after("<span class='fvc_selected'/>")
  var selected_label = element.next('.fvc_selected')

  header_div.after("<div class='fvc_expander'/>")
  var expander_div = header_div.next('.fvc_expander');

  if (opts.multi_select) {
    header_div.hide();
  } else {
    expander_div.hide();
  }

  header_div.button();

  // dataTables requires a unique ID
  var table_id = element.attr('id') + "_table";

  expander_div.html(
      "<table class='display tight_lines' id='" + table_id + "'>" + 
        "<thead>" +
        "  <tr>" +
        "    <th></th>" +
        "    <th></th>" +
        "    <th>Name</th>" +
        "    <th>Capacity</th>" +
        "    <th>Kind</th>" +
        "    <th>Status</th>" +
        "    <th>Primary server</th>" +
        "    <th>Failover server</th>" +
       "   </tr>" +
      "  </thead>" +
     "   <tbody>" +
    "    </tbody>" +
   "   </table>"
      );

  var select_widget_fn;
  if (!opts.multi_select) { 
    select_widget_fn = function() {return ""};
  } else {
    select_widget_fn = function(vol_info){return "<input type='checkbox' name='" + vol_info.id + "'/>";}
  }

  var table_element = expander_div.children('table')
  var volumeTable = table_element.dataTable({
    bServerSide: true,
    sAjaxSource: "volume/",
    bJQueryUI: true,
    bPaginate: false,
    bInfo: false,
    bProcessing: true,
    fnServerData: function(url, data, callback, settings) {
      Api.get_datatables(url, data, function(data){
        $.each(data.aaData, function(i, volume) {
          volume.primary_host_name = "---"
          volume.secondary_host_name = "---"
          $.each(volume.volume_nodes, function(i, node) {
            if (node.primary) {
              volume.primary_host_name = node.host_label
            } else if (node.use) {
              volume.secondary_host_name = node.host_label
            }
          });
          volume.select_widget = select_widget_fn(volume);
        });
        callback(data);
      }, settings, {category: 'usable'});
    },
    aoSort: [[2, 'asc']],
    aoColumns: [
      {sWidth: "1%", mDataProp: 'id', bSortable: false},
      {sWidth: "1%", mDataProp: 'select_widget', bSortable: false},
      {sWidth: "5%", mDataProp: 'label', bSortable: true},
      {sWidth: "1%", mDataProp: 'size', bSortable: false},
      {sWidth: "5%", mDataProp: 'kind', bSortable: false},
      {sWidth: "5%", mDataProp: 'status', bSortable: false},
      {sWidth: "5%", mDataProp: 'primary_host_name', bSortable: false},
      {sWidth: "5%", mDataProp: 'secondary_host_name', bSortable: false}
    ]
  });

  volumeTable.fnSetColumnVis(0, false);
  if (!opts.multi_select) {
    volumeTable.fnSetColumnVis(1, false);
  }

  table_element.delegate("td", "mouseenter", function() {
    $(this).parent().children().each(function() {
      $(this).addClass('rowhighlight')
    });
  });
  table_element.delegate("td", "mouseleave", function() {
    $(this).parent().children().each(function() {
      $(this).removeClass('rowhighlight')
    });
  });

  update_multi_select_value = function() {
    var selected = [];
    var checkboxes = table_element.find('input').each(function() {
      if ($(this).attr('checked')) {
        selected.push ($(this).attr('name'));
      }
    });

    fvc_instances[element.attr('id')].selected_lun_ids = selected
  }

  table_element.delegate("input", "click", function(event) {
    update_multi_select_value();

    event.stopPropagation();
  });

  table_element.delegate("tr", "click", function(event) {
    var aPos = volumeTable.fnGetPosition(this);
    var data = volumeTable.fnGetData(aPos);
    if (!opts.multi_select) {
      name = data.label;
      capacity = data.size;
      primary_server = data.primary_host_name;

      var selected_label = header_div.find('.fvc_selected')
      selected_label.html(name + " (" + capacity + ") on " + primary_server);

      fvc_instances[element.attr('id')].selected_lun_id = data.id

      // TODO: a close button or something for when there are no volumes (so no 'tr')
      header_div.show();
      expander_div.slideUp();
    } else {
      //console.log("multi select");
      var checked = $(this).find('input').attr('checked')
      $(this).find('input').attr('checked', !checked);

      update_multi_select_value();
    }

    if (opts.change) {
      opts.change();
    }
  });

  header_div.click(function() {
    header_div.hide();
    table_element.width("100%");
    
    expander_div.slideDown(null, function() {
    });
    
  });

  fvc_clear(element);
}

