require_relative '../model'

module Spaceship
  class ConnectAPI
    class Build
      include Spaceship::ConnectAPI::Model

      attr_accessor :version
      attr_accessor :uploaded_date
      attr_accessor :expiration_date
      attr_accessor :expired
      attr_accessor :min_os_version
      attr_accessor :icon_asset_token
      attr_accessor :processing_state
      attr_accessor :build_audience_type
      attr_accessor :uses_non_exempt_encryption

      self.attr_mapping({
        "version" => "version",
        "uploadedDate" => "uploaded_date",
        "expirationDate" => "expiration_date",
        "expired" => "expired",
        "minOsVersion" => "min_os_version",
        "iconAssetToken" => "icon_asset_token",
        "processingState" => "processing_state",
        "buildAudienceType" => "build_audience_type",
        "usesNonExemptEncryption" => "uses_non_exempt_encryption"
      })

      def self.type
        return "builds"
      end
    end
  end
end
