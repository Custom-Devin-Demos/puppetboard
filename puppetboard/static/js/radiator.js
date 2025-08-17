function resizeMe() {
  const preferredHeight = 944;
  const displayHeight = $(window).height();
  const percentageHeight = displayHeight / preferredHeight;

  const preferredWidth = 1100;
  const displayWidth = $(window).width();
  const percentageWidth = displayWidth / preferredWidth;

  let newFontSize;
  if (percentageHeight < percentageWidth) {
    newFontSize = Math.floor("960" * percentageHeight) - 30;
  } else {
    newFontSize = Math.floor("960" * percentageWidth) - 30;
  }
  $("body").css("font-size", newFontSize + "%")
}

$(document).ready(function() {
    $(window).on('resize', resizeMe).trigger('resize');
})
