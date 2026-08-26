cask "macmedic" do
  version "0.2.0"
  sha256 "REPLACE_WITH_SHA256_OF_RELEASE_ZIP"

  url "https://github.com/abhishek/macmedic/releases/download/v#{version}/MacMedic-#{version}.zip",
      verified: "github.com/abhishek/macmedic/"
  name "MacMedic"
  desc "Lightweight menu bar monitor and cleanup tool for aging Intel Macs"
  homepage "https://github.com/abhishek/macmedic"

  app "MacMedic.app"

  caveats <<~EOS
    MacMedic reads Intel SMC sensors (CPU temperature, fan RPM) via IOKit and
    needs no admin rights for monitoring. Fan control and system-modifying
    cleanup may require elevated access depending on the action.
  EOS
end